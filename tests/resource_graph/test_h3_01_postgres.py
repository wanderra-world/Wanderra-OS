"""PostgreSQL acceptance tests for H3-01 Resource Graph integrity."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.execution_context import ExecutionContextService
from app.resource_graph import (
    NoteKind,
    RelationshipKind,
    ResourceConcurrencyError,
    ResourceCreate,
    ResourceGraphError,
    ResourceGraphService,
    ResourceKind,
    ResourceRelationshipCreate,
)
from app.resource_graph.models import Resource, ResourceProjection, ResourceRelationship
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _migration,
    _require_migration,
    _seed_business_workspace,
)
from tests.provider_mirrors.test_h2_04_postgres import (
    NOW,
    _seed_connection,
)
from tests.provider_mirrors.test_h2_04_postgres import (
    _create as _create_mirror,
)
from tests.provider_mirrors.test_h2_04_postgres import (
    _service as _mirror_service,
)

H3_01_REVISION = "0022_h3_resource_graph"
H2_HEAD = "0021_h2_connection_cutover"
H3_TABLES = (
    "resource_projections",
    "resources",
    "resource_relationships",
    "resource_tags",
    "resource_attachments",
    "resource_notes",
    "resource_ownerships",
    "resource_grants",
    "resource_external_links",
)


class AllowAuthorizer:
    async def authorize(self, _context, _permission_key: str) -> bool:
        return True


class DenyAuthorizer:
    async def authorize(self, _context, _permission_key: str) -> bool:
        return False


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_01_additive_migration_forced_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H3_01_REVISION)
        _require_migration(database_name, H3_01_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert (
                await database.fetchval("SELECT version_num FROM alembic_version") == H3_01_REVISION
            )
            rows = await database.fetch(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE relname = ANY($1::text[])
                """,
                list(H3_TABLES),
            )
            assert {row["relname"] for row in rows} == set(H3_TABLES)
            assert all(row["relrowsecurity"] for row in rows)
            assert all(row["relforcerowsecurity"] for row in rows)
        finally:
            await database.close()
        _require_migration(database_name, H2_HEAD, direction="downgrade")
        _require_migration(database_name, H3_01_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_01_atomic_projection_relationship_rls_audit_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_01_REVISION)
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
        connection_id = await _seed_connection(sessions, execution, context)
        mirror_command = _create_mirror(connection_id)
        async with sessions() as session:
            async with execution.transaction(session, context):
                await _mirror_service(session, context).observe_new(
                    mirror_command,
                    idempotency_key="h3-01-provider-file",
                    now=NOW,
                )
        project_id = uuid4()
        task_id = uuid4()
        document_id = uuid4()

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = ResourceGraphService(session, context, authorizer=AllowAuthorizer())
                project = await service.create(
                    ResourceCreate(
                        resource_id=project_id,
                        projection_id=uuid4(),
                        kind=ResourceKind.PROJECT,
                    )
                )
                task = await service.create(
                    ResourceCreate(
                        resource_id=task_id,
                        projection_id=uuid4(),
                        kind=ResourceKind.TASK,
                    )
                )
                await service.create(
                    ResourceCreate(
                        resource_id=document_id,
                        projection_id=uuid4(),
                        kind=ResourceKind.DOCUMENT,
                    )
                )
                await service.relate(
                    ResourceRelationshipCreate(
                        relationship_id=uuid4(),
                        kind=RelationshipKind.PROJECT_HAS_TASK,
                        source_resource_id=project_id,
                        target_resource_id=task_id,
                    ),
                    expected_source_version=project.version,
                )
                await service.add_tag(
                    resource_id=project_id,
                    tag="Priority",
                    expected_version=2,
                )
                await service.add_note(
                    note_id=uuid4(),
                    resource_id=project_id,
                    kind=NoteKind.AI,
                    content="Synthetic H3-01 acceptance note",
                    model_reference="synthetic-model-v1",
                    expected_version=3,
                )
                await service.attach(
                    attachment_id=uuid4(),
                    resource_id=project_id,
                    attachment_resource_id=document_id,
                    expected_version=4,
                )
                with pytest.raises(ResourceGraphError, match="active workspace member"):
                    await service.assign_owner(
                        resource_id=project_id,
                        owner_user_id=uuid4(),
                        expected_version=5,
                    )
                await service.assign_owner(
                    resource_id=project_id,
                    owner_user_id=owner_id,
                    expected_version=5,
                )
                with pytest.raises(ResourceGraphError, match="active workspace member"):
                    await service.grant(
                        grant_id=uuid4(),
                        resource_id=project_id,
                        grantee_user_id=uuid4(),
                        permission_key="read_content",
                        expected_version=6,
                    )
                await service.grant(
                    grant_id=uuid4(),
                    resource_id=project_id,
                    grantee_user_id=owner_id,
                    permission_key="read_content",
                    expected_version=6,
                )
                await service.link_external_reference(
                    link_id=uuid4(),
                    resource_id=project_id,
                    external_reference_id=mirror_command.external_reference_id,
                    expected_version=7,
                )
                granted_read = await ResourceGraphService(
                    session, context, authorizer=DenyAuthorizer()
                ).get(project_id)
                assert granted_read.id == project_id
                with pytest.raises(ResourceConcurrencyError):
                    await service.add_tag(
                        resource_id=project_id,
                        tag="stale",
                        expected_version=1,
                    )
                await service.delete(
                    resource_id=task_id,
                    expected_version=task.version,
                )

            async with execution.transaction(session, context):
                assert await session.scalar(select(func.count()).select_from(Resource)) == 3
                assert (
                    await session.scalar(select(func.count()).select_from(ResourceProjection)) == 3
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.target_type == "resource")
                    )
                    == 11
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.aggregate_type == "resource")
                    )
                    == 11
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ResourceRelationship)
                        .where(ResourceRelationship.status == "active")
                    )
                    == 0
                )

            async with execution.transaction(session, other_context):
                with pytest.raises(ResourceGraphError, match="does not exist"):
                    await ResourceGraphService(
                        session, other_context, authorizer=AllowAuthorizer()
                    ).get(project_id)

        downgrade = _migration(database_name, H2_HEAD, direction="downgrade")
        assert downgrade.returncode != 0
        assert "reviewed forward fix" in downgrade.stderr
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_01_deferred_pair_constraints_reject_orphan_resource() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H3_01_REVISION)
        organization_id, workspace_id, _, owner_id, _ = await _seed_business_workspace(
            database_name
        )
        database = await asyncpg.connect(_database_url(database_name))
        try:
            cell_id = await database.fetchval(
                "SELECT cell_id FROM workspaces WHERE workspace_id = $1",
                workspace_id,
            )
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                async with database.transaction():
                    await database.execute(
                        """
                        INSERT INTO resources (
                          organization_id, workspace_id, cell_id, id,
                          resource_type, projection_id, created_by_user_id
                        ) VALUES ($1,$2,$3,$4,'project',$5,$6)
                        """,
                        organization_id,
                        workspace_id,
                        cell_id,
                        uuid4(),
                        uuid4(),
                        owner_id,
                    )
        finally:
            await database.close()
    finally:
        await _drop_database(admin, database_name)
        await admin.close()
