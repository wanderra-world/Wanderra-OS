"""PostgreSQL acceptance tests for H3-04 knowledge and timeline."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.documents import (
    Classification,
    DocumentCreate,
    DocumentService,
    DocumentVersionCreate,
    ExtractionRequest,
)
from app.documents.models import DocumentChunk
from app.execution_context import ExecutionContextService
from app.knowledge import (
    ClaimCreate,
    ClaimEvidence,
    ClaimValueType,
    KnowledgeService,
    TimelineInput,
)
from app.knowledge.contracts import ContradictionCreate, KnowledgeError, ReviewState
from app.knowledge.models import (
    KnowledgeClaim,
    KnowledgeEvidence,
    KnowledgeSourceDisposition,
    TimelineCheckpoint,
    TimelineEntry,
)
from app.resource_graph import ResourceCreate, ResourceGraphService, ResourceKind
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.documents.test_h3_03_postgres import (
    AllowAuthorizer,
    CleanVerifier,
    ExtractionJobs,
    MemoryObjectStorage,
    PlainTextExtractor,
)
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
    _seed_business_workspace,
)

H3_04_REVISION = "0025_h3_knowledge_timeline"
H3_03_HEAD = "0024_h3_document_custody"
H3_04_TABLES = (
    "knowledge_claims",
    "knowledge_evidence",
    "knowledge_relations",
    "knowledge_source_dispositions",
    "timeline_entries",
    "timeline_checkpoints",
)
NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


class DispositionJobs(ExtractionJobs):
    def __init__(self) -> None:
        super().__init__()
        self.dispositions = []

    async def enqueue_source_disposition(self, source_version_id):
        self.dispositions.append(source_version_id)
        return uuid4()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_04_additive_migration_forced_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H3_04_REVISION)
        _require_migration(database_name, H3_04_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert (
                await database.fetchval("SELECT version_num FROM alembic_version") == H3_04_REVISION
            )
            rows = await database.fetch(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE relname = ANY($1::text[])
                """,
                list(H3_04_TABLES),
            )
            assert {row["relname"] for row in rows} == set(H3_04_TABLES)
            assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)
        finally:
            await database.close()
        _require_migration(database_name, H3_03_HEAD, direction="downgrade")
        _require_migration(database_name, H3_04_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_04_claim_timeline_disposition_rls_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_04_REVISION)
        (
            organization_id,
            workspace_id,
            other_workspace_id,
            owner_id,
            _,
        ) = await _seed_business_workspace(database_name)
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        other_context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=other_workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        storage, jobs = MemoryObjectStorage(), DispositionJobs()
        resource_id, projection_id, document_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
        content = b"Stockholm|Gothenburg"
        async with sessions() as session:
            async with execution.transaction(session, context):
                graph = ResourceGraphService(session, context, authorizer=AllowAuthorizer())
                await graph.create(
                    ResourceCreate(
                        resource_id=resource_id,
                        projection_id=projection_id,
                        kind=ResourceKind.DOCUMENT,
                    ),
                    now=NOW,
                )
                documents = DocumentService(
                    session,
                    context,
                    object_storage=storage,
                    authorizer=AllowAuthorizer(),
                    extraction_jobs=jobs,
                    deletion_jobs=jobs,
                )
                await documents.create(
                    DocumentCreate(
                        document_id=document_id,
                        resource_id=resource_id,
                        title="Company locations",
                        classification=Classification.CONFIDENTIAL,
                        classification_policy_version=1,
                    ),
                    now=NOW,
                )
                await documents.ingest(
                    DocumentVersionCreate(
                        version_id=version_id,
                        document_id=document_id,
                        content=content,
                        expected_sha256=hashlib.sha256(content).hexdigest(),
                        media_type="text/plain",
                        classification=Classification.CONFIDENTIAL,
                        classification_policy_version=1,
                        encryption_key_version=1,
                    ),
                    now=NOW,
                )
                await documents.verify(version_id, verifier=CleanVerifier(), now=NOW)
                derivative = await documents.complete_extraction(
                    ExtractionRequest(
                        derivative_id=uuid4(),
                        version_id=version_id,
                        processor_key="plain-text",
                        processor_version="1",
                        classification=Classification.CONFIDENTIAL,
                        policy_version=1,
                    ),
                    extractor=PlainTextExtractor(),
                    now=NOW,
                )
                chunk = (
                    await session.scalars(
                        select(DocumentChunk)
                        .where(DocumentChunk.derivative_id == derivative.id)
                        .order_by(DocumentChunk.position)
                    )
                ).first()
                assert chunk is not None
                knowledge = KnowledgeService(
                    session, context, authorizer=AllowAuthorizer(), disposition_jobs=jobs
                )
                claim_command = ClaimCreate(
                    claim_id=uuid4(),
                    subject_resource_id=resource_id,
                    predicate="company.location",
                    value_type=ClaimValueType.TEXT,
                    value="Stockholm",
                    confidence=0.95,
                    extractor_key="synthetic.claims",
                    extractor_version="1",
                    classification=Classification.CONFIDENTIAL,
                    policy_version=1,
                )
                claim_evidence = (
                    ClaimEvidence(
                        evidence_id=uuid4(),
                        source_version_id=version_id,
                        source_chunk_id=chunk.id,
                        source_hash=chunk.content_hash,
                        span_start=0,
                        span_end=len(chunk.content),
                        classification=Classification.CONFIDENTIAL,
                        policy_version=1,
                    ),
                )
                claim = await knowledge.create_claim(claim_command, claim_evidence, now=NOW)
                assert (
                    await knowledge.create_claim(claim_command, claim_evidence, now=NOW)
                ).id == claim.id
                changed_evidence = (
                    ClaimEvidence(
                        evidence_id=uuid4(),
                        source_version_id=version_id,
                        source_chunk_id=chunk.id,
                        source_hash=chunk.content_hash,
                        span_start=0,
                        span_end=len(chunk.content) - 1,
                        classification=Classification.CONFIDENTIAL,
                        policy_version=1,
                    ),
                )
                with pytest.raises(KnowledgeError, match="changed derivation input"):
                    await knowledge.create_claim(claim_command, changed_evidence, now=NOW)
                await knowledge.review_claim(
                    claim.id,
                    state=ReviewState.ACCEPTED,
                    reason="synthetic reviewer evidence",
                    now=NOW,
                )
                second = await knowledge.create_claim(
                    ClaimCreate(
                        claim_id=uuid4(),
                        subject_resource_id=resource_id,
                        predicate="company.location",
                        value_type=ClaimValueType.TEXT,
                        value="Gothenburg",
                        confidence=0.8,
                        extractor_key="synthetic.claims",
                        extractor_version="1",
                        classification=Classification.CONFIDENTIAL,
                        policy_version=1,
                    ),
                    (
                        ClaimEvidence(
                            evidence_id=uuid4(),
                            source_version_id=version_id,
                            source_chunk_id=chunk.id,
                            source_hash=chunk.content_hash,
                            span_start=0,
                            span_end=len(chunk.content),
                            classification=Classification.CONFIDENTIAL,
                            policy_version=1,
                        ),
                    ),
                    now=NOW,
                )
                await knowledge.relate_claims(
                    ContradictionCreate(
                        relation_id=uuid4(),
                        claim_id=claim.id,
                        conflicting_claim_id=second.id,
                        relation_type="contradicts",
                        reason="two explicit candidates",
                    ),
                    now=NOW,
                )
                timeline = TimelineInput(
                    source_event_id=uuid4(),
                    source_event_type="knowledge.claim.created",
                    source_sequence=1,
                    occurred_at=NOW,
                    resource_id=resource_id,
                    source_claim_id=claim.id,
                    title="Location evidence recorded",
                    visibility="restricted",
                    classification=Classification.CONFIDENTIAL,
                    policy_version=1,
                )
                entry = await knowledge.project_timeline(timeline, now=NOW)
                assert (await knowledge.project_timeline(timeline, now=NOW)).id == entry.id
                checkpoint = await knowledge.rebuild_timeline((timeline,), now=NOW)
                assert checkpoint.entry_count == 1 and len(checkpoint.checksum) == 64
                disposition = await knowledge.request_source_disposition(version_id)
                assert jobs.dispositions == [version_id]
                assert (await knowledge.request_source_disposition(version_id)).id == disposition.id
                assert jobs.dispositions == [version_id]
                assert await knowledge.process_source_disposition(disposition.id, now=NOW)
                assert (
                    await knowledge.process_source_disposition(disposition.id, now=NOW)
                ).status == "completed"
                with pytest.raises(KnowledgeError, match="invalidated"):
                    await knowledge.claim(claim.id)
                manifest = await knowledge.export_manifest()
                assert len(manifest["claims"]) == 2
                assert len(manifest["evidence"]) == 2
                assert len(manifest["relations"]) == 1
                assert manifest["relations"][0]["classification"] == "confidential"
                assert manifest["relations"][0]["policy_version"] == 1
                assert manifest["source_dispositions"] == [
                    {
                        "disposition_id": str(disposition.id),
                        "source_version_id": str(version_id),
                        "status": "completed",
                        "exception_code": None,
                    }
                ]
                assert manifest["timeline_checkpoint"]["checksum"] == checkpoint.checksum
            async with execution.transaction(session, context):
                assert await session.scalar(select(func.count()).select_from(KnowledgeClaim)) == 2
                assert (
                    await session.scalar(select(func.count()).select_from(KnowledgeEvidence)) == 2
                )
                assert (
                    await session.scalar(select(func.count()).select_from(TimelineCheckpoint)) == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(KnowledgeSourceDisposition)
                    )
                    == 1
                )
                stored_entry = await session.scalar(select(TimelineEntry))
                assert stored_entry is not None and stored_entry.status == "removed"
                assert await session.scalar(select(func.count()).select_from(AuditEvent)) >= 10
                assert await session.scalar(select(func.count()).select_from(OutboxEvent)) >= 10
            async with execution.transaction(session, other_context):
                with pytest.raises(KnowledgeError, match="does not exist"):
                    await KnowledgeService(
                        session, other_context, authorizer=AllowAuthorizer()
                    ).claim(claim.id)
        database = await asyncpg.connect(_database_url(database_name))
        role = f"h3_04_reader_{uuid4().hex[:12]}"
        try:
            await database.execute(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS")
            await database.execute(f"GRANT SELECT ON {', '.join(H3_04_TABLES)} TO {role}")
            await database.execute(f"SET ROLE {role}")
            await database.execute(
                "SELECT set_config('atlas.organization_id', $1, false), "
                "set_config('atlas.workspace_id', $2, false), "
                "set_config('atlas.cell_id', $3, false)",
                str(context.tenant.organization_id),
                str(context.tenant.workspace_id),
                str(context.tenant.cell_id),
            )
            assert await database.fetchval("SELECT count(*) FROM knowledge_claims") == 2
            await database.execute(
                "SELECT set_config('atlas.workspace_id', $1, false), "
                "set_config('atlas.cell_id', $2, false)",
                str(other_context.tenant.workspace_id),
                str(other_context.tenant.cell_id),
            )
            assert await database.fetchval("SELECT count(*) FROM knowledge_claims") == 0
        finally:
            await database.execute("RESET ROLE")
            await database.execute(f"REVOKE SELECT ON {', '.join(H3_04_TABLES)} FROM {role}")
            await database.execute(f"DROP ROLE IF EXISTS {role}")
            await database.close()
        with pytest.raises(Exception, match="reviewed forward fix"):
            _require_migration(database_name, H3_03_HEAD, direction="downgrade")
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
