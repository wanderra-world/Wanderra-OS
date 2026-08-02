"""PostgreSQL acceptance tests for H3-03 document custody and derivation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.documents import (
    Classification,
    CustodyError,
    DocumentCreate,
    DocumentService,
    DocumentVersionCreate,
    ExtractionRequest,
    MalwareVerdict,
    VerificationEvidence,
)
from app.documents.models import (
    Document,
    DocumentChunk,
    DocumentDeletion,
    DocumentDerivative,
    DocumentVersion,
)
from app.execution_context import ExecutionContextService
from app.resource_graph import ResourceCreate, ResourceGraphService, ResourceKind
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
    _seed_business_workspace,
)

H3_03_REVISION = "0024_h3_document_custody"
H3_02_HEAD = "0023_h3_durable_execution"
H3_03_TABLES = (
    "documents",
    "document_versions",
    "document_derivatives",
    "document_chunks",
    "document_deletions",
)
NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


class AllowAuthorizer:
    async def authorize(self, _context, _permission_key: str) -> bool:
        return True


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_delete: set[str] = set()

    async def put_quarantined(self, key: str, content: bytes) -> None:
        self.objects.setdefault(key, content)

    async def promote(self, quarantine_key: str, object_key: str) -> None:
        self.objects[object_key] = self.objects[quarantine_key]

    async def read(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        if key in self.fail_delete:
            raise RuntimeError("synthetic object deletion failure")
        self.objects.pop(key, None)


class CleanVerifier:
    async def verify(self, content: bytes, _media_type: str) -> VerificationEvidence:
        return VerificationEvidence(
            content_hash=hashlib.sha256(content).hexdigest(),
            malware_verdict=MalwareVerdict.CLEAN,
            media_type_verified=True,
            verified_at=NOW,
            verifier_version="synthetic-scanner/1",
        )


class PlainTextExtractor:
    async def extract(self, content: bytes, _media_type: str) -> tuple[str, ...]:
        return tuple(part for part in content.decode().split("|") if part)


class ExtractionJobs:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []
        self.deletions: list[tuple[UUID, UUID]] = []

    async def enqueue_extraction(self, version_id: UUID, input_digest: str) -> UUID:
        self.calls.append((version_id, input_digest))
        return uuid4()

    async def enqueue_deletion(self, deletion_id: UUID, document_id: UUID) -> UUID:
        self.deletions.append((deletion_id, document_id))
        return uuid4()


def _service(session, context, storage, *, jobs=None) -> DocumentService:
    return DocumentService(
        session,
        context,
        object_storage=storage,
        authorizer=AllowAuthorizer(),
        extraction_jobs=jobs,
        deletion_jobs=jobs,
    )


async def _create_document_resource(
    session, context, resource_id: UUID, projection_id: UUID
) -> None:
    await ResourceGraphService(
        session,
        context,
        authorizer=AllowAuthorizer(),
    ).create(
        ResourceCreate(
            resource_id=resource_id,
            projection_id=projection_id,
            kind=ResourceKind.DOCUMENT,
        ),
        now=NOW,
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_03_additive_migration_forced_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H3_03_REVISION)
        _require_migration(database_name, H3_03_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert (
                await database.fetchval("SELECT version_num FROM alembic_version") == H3_03_REVISION
            )
            rows = await database.fetch(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE relname = ANY($1::text[])
                """,
                list(H3_03_TABLES),
            )
            assert {row["relname"] for row in rows} == set(H3_03_TABLES)
            assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)
        finally:
            await database.close()
        _require_migration(database_name, H3_02_HEAD, direction="downgrade")
        _require_migration(database_name, H3_03_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_03_custody_extraction_replay_lineage_and_audit() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_03_REVISION)
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
        storage = MemoryObjectStorage()
        jobs = ExtractionJobs()
        resource_id, projection_id, document_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
        content = b"first|second"
        digest = hashlib.sha256(content).hexdigest()
        async with sessions() as session:
            async with execution.transaction(session, context):
                await _create_document_resource(session, context, resource_id, projection_id)
                service = _service(session, context, storage, jobs=jobs)
                await service.create(
                    DocumentCreate(
                        document_id=document_id,
                        resource_id=resource_id,
                        title="Synthetic evidence",
                        classification=Classification.CONFIDENTIAL,
                        classification_policy_version=1,
                    ),
                    now=NOW,
                )
                version = await service.ingest(
                    DocumentVersionCreate(
                        version_id=version_id,
                        document_id=document_id,
                        content=content,
                        expected_sha256=digest,
                        media_type="text/plain",
                        classification=Classification.CONFIDENTIAL,
                        classification_policy_version=1,
                        encryption_key_version=1,
                    ),
                    now=NOW,
                )
                assert version.custody_status == "quarantined"
                with pytest.raises(CustodyError):
                    await service.complete_extraction(
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
                await service.verify(version_id, verifier=CleanVerifier(), now=NOW)
                job_id = await service.request_extraction(
                    ExtractionRequest(
                        derivative_id=uuid4(),
                        version_id=version_id,
                        processor_key="plain-text",
                        processor_version="1",
                        classification=Classification.CONFIDENTIAL,
                        policy_version=1,
                    )
                )
                assert job_id is not None and len(jobs.calls) == 1
                request = ExtractionRequest(
                    derivative_id=uuid4(),
                    version_id=version_id,
                    processor_key="plain-text",
                    processor_version="1",
                    classification=Classification.CONFIDENTIAL,
                    policy_version=1,
                )
                first = await service.complete_extraction(
                    request,
                    extractor=PlainTextExtractor(),
                    now=NOW,
                )
                replay = await service.complete_extraction(
                    request,
                    extractor=PlainTextExtractor(),
                    now=NOW,
                )
                assert replay.id == first.id
                manifest = await service.export_manifest(document_id)
                assert manifest["versions"] == [
                    {
                        "version_id": str(version_id),
                        "content_hash": digest,
                        "custody_status": "verified",
                        "object_key": version.object_key,
                        "encryption_key_version": 1,
                    }
                ]
                assert await service.verify_restore(version_id)
            async with execution.transaction(session, context):
                derivative = await session.scalar(select(DocumentDerivative))
                assert derivative is not None and derivative.source_version_id == version_id
                assert await session.scalar(select(func.count()).select_from(DocumentChunk)) == 2
                assert await session.scalar(select(func.count()).select_from(AuditEvent)) >= 5
                assert await session.scalar(select(func.count()).select_from(OutboxEvent)) >= 5
            async with execution.transaction(session, other_context):
                with pytest.raises(CustodyError, match="does not exist"):
                    await _service(session, other_context, storage).verify_restore(version_id)
        database = await asyncpg.connect(_database_url(database_name))
        rls_role = f"h3_03_reader_{uuid4().hex[:12]}"
        try:
            await database.execute(f"CREATE ROLE {rls_role} NOLOGIN NOSUPERUSER NOBYPASSRLS")
            await database.execute(f"GRANT SELECT ON {', '.join(H3_03_TABLES)} TO {rls_role}")
            await database.execute(f"SET ROLE {rls_role}")
            await database.execute(
                "SELECT set_config('atlas.organization_id', $1, false), "
                "set_config('atlas.workspace_id', $2, false), "
                "set_config('atlas.cell_id', $3, false)",
                str(context.tenant.organization_id),
                str(context.tenant.workspace_id),
                str(context.tenant.cell_id),
            )
            assert await database.fetchval("SELECT count(*) FROM documents") == 1
            await database.execute(
                "SELECT set_config('atlas.workspace_id', $1, false), "
                "set_config('atlas.cell_id', $2, false)",
                str(other_context.tenant.workspace_id),
                str(other_context.tenant.cell_id),
            )
            assert await database.fetchval("SELECT count(*) FROM documents") == 0
        finally:
            await database.execute("RESET ROLE")
            await database.execute(f"REVOKE SELECT ON {', '.join(H3_03_TABLES)} FROM {rls_role}")
            await database.execute(f"DROP ROLE IF EXISTS {rls_role}")
            await database.close()
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_03_retention_deletion_exception_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_03_REVISION)
        organization_id, workspace_id, _, owner_id, _ = await _seed_business_workspace(
            database_name
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        storage = MemoryObjectStorage()
        jobs = ExtractionJobs()
        document_id, version_id = uuid4(), uuid4()
        content = b"retained"
        async with sessions() as session:
            async with execution.transaction(session, context):
                resource_id, projection_id = uuid4(), uuid4()
                await _create_document_resource(session, context, resource_id, projection_id)
                service = _service(session, context, storage, jobs=jobs)
                await service.create(
                    DocumentCreate(
                        document_id=document_id,
                        resource_id=resource_id,
                        title="Governed evidence",
                        classification=Classification.INTERNAL,
                        classification_policy_version=1,
                        legal_hold=True,
                        retain_until=NOW + timedelta(days=30),
                    ),
                    now=NOW,
                )
                await service.ingest(
                    DocumentVersionCreate(
                        version_id=version_id,
                        document_id=document_id,
                        content=content,
                        expected_sha256=hashlib.sha256(content).hexdigest(),
                        media_type="text/plain",
                        classification=Classification.INTERNAL,
                        classification_policy_version=1,
                        encryption_key_version=1,
                    ),
                    now=NOW,
                )
                blocked = await service.delete(document_id, reason="user request", now=NOW)
                assert blocked.status == "blocked" and blocked.disposition == "legal_hold"
                await service.set_governance(
                    document_id,
                    legal_hold=False,
                    retain_until=NOW - timedelta(seconds=1),
                    reason="authorized hold release",
                    now=NOW,
                )
                await service.verify(version_id, verifier=CleanVerifier(), now=NOW)
                version = await session.scalar(
                    select(DocumentVersion).where(DocumentVersion.id == version_id)
                )
                assert version is not None
                storage.fail_delete.add(version.object_key)
                requested = await service.delete(document_id, reason="eligible erasure", now=NOW)
                assert requested.status == "pending" and len(jobs.deletions) == 1
            async with execution.transaction(session, context):
                service = _service(session, context, storage, jobs=jobs)
                failed = await service.process_deletion(requested.id, now=NOW)
                assert (
                    failed.status == "exception" and failed.exception_code == "object_delete_failed"
                )
                storage.fail_delete.clear()
            async with execution.transaction(session, context):
                service = _service(session, context, storage, jobs=jobs)
                completed = await service.process_deletion(requested.id, now=NOW)
                assert completed.status == "completed"
            async with execution.transaction(session, context):
                assert await session.scalar(select(func.count()).select_from(DocumentDeletion)) == 2
                document = await session.scalar(select(Document).where(Document.id == document_id))
                assert document is not None and document.status == "deleted"
        with pytest.raises(Exception, match="reviewed forward fix"):
            _require_migration(database_name, H3_02_HEAD, direction="downgrade")
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
