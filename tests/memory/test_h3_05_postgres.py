"""PostgreSQL, RLS, lifecycle, idempotency, and rollback evidence for H3-05."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.documents import Classification
from app.execution_context import ExecutionContextService
from app.memory import (
    ConsolidationCreate,
    GovernedMemoryService,
    MemoryCreate,
    MemoryFeedbackCreate,
    MemoryFeedbackKind,
    MemoryKind,
    MemorySource,
    MemorySourceKind,
    MemoryStatus,
    MemoryVisibility,
)
from app.memory.governance_contracts import MemoryError, versioned_source_digest
from app.memory.governed_models import (
    GovernedMemoryDisposition,
    GovernedMemoryFeedback,
    GovernedMemoryItem,
    GovernedMemorySource,
)
from app.resource_graph import ResourceCreate, ResourceGraphService, ResourceKind
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.documents.test_h3_03_postgres import AllowAuthorizer
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
)

H3_05_REVISION = "0026_h3_governed_memory"
H3_04_HEAD = "0025_h3_knowledge_timeline"
H3_05_TABLES = (
    "governed_memory_items",
    "governed_memory_sources",
    "governed_memory_feedback",
    "governed_memory_dispositions",
)
NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


def _command(*, owner_id, resource_id, content: str, expires_at=None) -> MemoryCreate:
    return MemoryCreate(
        memory_id=uuid4(),
        memory_kind=MemoryKind.WORKING_FACT,
        content=content,
        subject_resource_id=resource_id,
        owner_user_id=owner_id,
        visibility=MemoryVisibility.WORKSPACE,
        confidence=0.9,
        classification=Classification.INTERNAL,
        policy_version=1,
        creation_method="derived",
        expires_at=expires_at,
        sources=(
            MemorySource(
                source_id=resource_id,
                source_kind=MemorySourceKind.RESOURCE,
                source_version=1,
                source_digest=versioned_source_digest(MemorySourceKind.RESOURCE, resource_id, 1),
                classification=Classification.INTERNAL,
                policy_version=1,
            ),
        ),
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_05_additive_migration_forced_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H3_05_REVISION)
        _require_migration(database_name, H3_05_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval("SELECT version_num FROM alembic_version") == (
                H3_05_REVISION
            )
            rows = await database.fetch(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE relname = ANY($1::text[])
                """,
                list(H3_05_TABLES),
            )
            assert {row["relname"] for row in rows} == set(H3_05_TABLES)
            assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)
        finally:
            await database.close()
        _require_migration(database_name, H3_04_HEAD, direction="downgrade")
        _require_migration(database_name, H3_05_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_05_memory_lifecycle_provenance_rls_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_05_REVISION)
        from tests.memberships.test_h1_04_postgres import _seed_business_workspace

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
        resource_id = uuid4()
        first_id = second_id = consolidated_id = expiring_id = None
        async with sessions() as session:
            async with execution.transaction(session, context):
                graph = ResourceGraphService(session, context, authorizer=AllowAuthorizer())
                await graph.create(
                    ResourceCreate(
                        resource_id=resource_id,
                        projection_id=uuid4(),
                        kind=ResourceKind.PROJECT,
                    ),
                    now=NOW,
                )
                service = GovernedMemoryService(session, context, authorizer=AllowAuthorizer())
                first_command = _command(
                    owner_id=owner_id, resource_id=resource_id, content="Use immutable receipts."
                )
                first = await service.create(first_command, now=NOW)
                first_id = first.id
                replay = await service.create(replace(first_command, memory_id=uuid4()), now=NOW)
                assert replay.id == first.id
                await service.set_pinned(first.id, True, now=NOW)
                await service.confirm(first.id, now=NOW)
                feedback = await service.add_feedback(
                    MemoryFeedbackCreate(
                        feedback_id=uuid4(),
                        memory_id=first.id,
                        kind=MemoryFeedbackKind.HELPFUL,
                        reason="Confirmed during recovery rehearsal.",
                    ),
                    now=NOW,
                )
                assert feedback.memory_id == first.id

                second = await service.create(
                    _command(
                        owner_id=owner_id,
                        resource_id=resource_id,
                        content="Require two recovery custodians.",
                    ),
                    now=NOW,
                )
                second_id = second.id
                consolidation = ConsolidationCreate(
                    memory_id=uuid4(),
                    input_memory_ids=(first.id, second.id),
                    processor_key="atlas.memory.consolidate",
                    processor_version="1",
                    policy_version=1,
                )
                ordered = tuple(sorted((first, second), key=lambda item: item.id))
                consolidated = await service.consolidate(
                    consolidation,
                    MemoryCreate(
                        memory_id=consolidation.memory_id,
                        memory_kind=MemoryKind.SUMMARY,
                        content="Recovery requires immutable receipts and two custodians.",
                        subject_resource_id=resource_id,
                        owner_user_id=owner_id,
                        visibility=MemoryVisibility.WORKSPACE,
                        confidence=0.9,
                        classification=Classification.INTERNAL,
                        policy_version=1,
                        creation_method="consolidated",
                        expires_at=None,
                        sources=tuple(
                            MemorySource(
                                source_id=item.id,
                                source_kind=MemorySourceKind.MEMORY_ITEM,
                                source_version=item.state_version,
                                source_digest=item.identity_digest,
                                classification=Classification(item.classification),
                                policy_version=item.policy_version,
                            )
                            for item in ordered
                        ),
                    ),
                    now=NOW,
                )
                consolidated_id = consolidated.id
                assert consolidated.input_digest == consolidation.input_digest

                expiring = await service.create(
                    _command(
                        owner_id=owner_id,
                        resource_id=resource_id,
                        content="Temporary recovery rehearsal note.",
                        expires_at=NOW + timedelta(hours=1),
                    ),
                    now=NOW,
                )
                expiring_id = expiring.id
                expired = await service.expire_due(now=NOW + timedelta(hours=1))
                assert [item.id for item in expired] == [expiring.id]
                assert expiring.status == MemoryStatus.EXPIRED.value

                invalidated = await service.dispose_source(
                    MemorySourceKind.RESOURCE, resource_id, now=NOW + timedelta(hours=2)
                )
                assert {item.id for item in invalidated} >= {
                    first.id,
                    second.id,
                    consolidated.id,
                }
                assert first.status == MemoryStatus.INVALIDATED.value
                manifest = await service.export_manifest()
                assert len(manifest["memories"]) == 4
                assert len(manifest["feedback"]) == 1
                assert len(manifest["dispositions"]) == 4

            async with execution.transaction(session, context):
                assert (
                    await session.scalar(select(func.count()).select_from(GovernedMemoryItem)) == 4
                )
                assert (
                    await session.scalar(select(func.count()).select_from(GovernedMemorySource))
                    == 5
                )
                assert (
                    await session.scalar(select(func.count()).select_from(GovernedMemoryFeedback))
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GovernedMemoryDisposition)
                    )
                    == 4
                )
                assert await session.scalar(select(func.count()).select_from(AuditEvent)) >= 12
                assert await session.scalar(select(func.count()).select_from(OutboxEvent)) >= 12
            async with execution.transaction(session, other_context):
                with pytest.raises(MemoryError, match="does not exist"):
                    await GovernedMemoryService(
                        session, other_context, authorizer=AllowAuthorizer()
                    ).get(first_id)

        assert all(
            value is not None for value in (first_id, second_id, consolidated_id, expiring_id)
        )
        database = await asyncpg.connect(_database_url(database_name))
        role = f"h3_05_reader_{uuid4().hex[:12]}"
        try:
            await database.execute(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS")
            await database.execute(f"GRANT SELECT ON {', '.join(H3_05_TABLES)} TO {role}")
            await database.execute(f"SET ROLE {role}")
            await database.execute(
                "SELECT set_config('atlas.organization_id', $1, false), "
                "set_config('atlas.workspace_id', $2, false), "
                "set_config('atlas.cell_id', $3, false)",
                str(context.tenant.organization_id),
                str(context.tenant.workspace_id),
                str(context.tenant.cell_id),
            )
            assert await database.fetchval("SELECT count(*) FROM governed_memory_items") == 4
            await database.execute(
                "SELECT set_config('atlas.workspace_id', $1, false), "
                "set_config('atlas.cell_id', $2, false)",
                str(other_context.tenant.workspace_id),
                str(other_context.tenant.cell_id),
            )
            assert await database.fetchval("SELECT count(*) FROM governed_memory_items") == 0
        finally:
            await database.execute("RESET ROLE")
            await database.execute(f"REVOKE SELECT ON {', '.join(H3_05_TABLES)} FROM {role}")
            await database.execute(f"DROP ROLE IF EXISTS {role}")
            await database.close()
        with pytest.raises(Exception, match="reviewed forward fix"):
            _require_migration(database_name, H3_04_HEAD, direction="downgrade")
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
