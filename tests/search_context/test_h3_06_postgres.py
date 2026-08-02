"""PostgreSQL, pgvector, RLS, disposal, and rollback evidence for H3-06."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.execution_context import ExecutionContextService
from app.search_context import Classification, SearchDocumentInput, SearchQuery
from app.search_context.service import SearchContextService
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.documents.test_h3_03_postgres import AllowAuthorizer
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
)

REVISION = "0027_h3_search_context"
PREVIOUS = "0026_h3_governed_memory"
TABLES = (
    "search_index_generations",
    "search_documents",
    "search_acl_projections",
    "search_embeddings",
    "search_reconciliations",
)


class DeterministicEmbedding:
    model_key = "test.semantic"
    model_version = "1"
    dimensions = 3

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "semantic" in text else [0.0, 1.0, 0.0]


@pytest.mark.skipif(SOURCE_DATABASE_URL is None, reason="PostgreSQL URL is required")
async def test_h3_06_pgvector_forced_rls_empty_rollback() -> None:
    admin, name = await _create_database()
    try:
        _require_migration(name, REVISION)
        database = await asyncpg.connect(_database_url(name))
        try:
            assert await database.fetchval(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            )
            rows = await database.fetch(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY($1::text[])",
                list(TABLES),
            )
            assert {row["relname"] for row in rows} == set(TABLES)
            assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)
        finally:
            await database.close()
        _require_migration(name, PREVIOUS, direction="downgrade")
        _require_migration(name, REVISION)
    finally:
        await _drop_database(admin, name)
        await admin.close()


@pytest.mark.skipif(SOURCE_DATABASE_URL is None, reason="PostgreSQL URL is required")
async def test_h3_06_lexical_disposition_audit_and_guarded_rollback() -> None:
    admin, name = await _create_database()
    engine = None
    try:
        _require_migration(name, REVISION)
        from tests.memberships.test_h1_04_postgres import _seed_business_workspace

        (
            organization_id,
            workspace_id,
            other_workspace_id,
            owner_id,
            _,
        ) = await _seed_business_workspace(name)
        context = await _context_for_owner(
            name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        other_context = await _context_for_owner(
            name,
            organization_id=organization_id,
            workspace_id=other_workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        source_id = uuid4()
        async with sessions() as session:
            async with ExecutionContextService().transaction(session, context):
                service = SearchContextService(session, context, authorizer=AllowAuthorizer())
                generation = await service.create_generation(
                    generation_id=uuid4(),
                    index_version="h3-06-v1",
                    chunker_version="source-v1",
                    policy_version=1,
                    manifest_digest="a" * 64,
                )
                await service.index(
                    generation.id,
                    SearchDocumentInput(
                        source_kind="document_version",
                        source_id=source_id,
                        source_version=1,
                        source_digest="b" * 64,
                        title="Atlas recovery",
                        content="Deterministic recovery evidence",
                        classification=Classification.INTERNAL,
                        visibility="workspace",
                        policy_version=1,
                    ),
                    now=datetime(2026, 8, 2, tzinfo=UTC),
                )
                await service.activate_generation(generation.id)
                assert len(await service.search(SearchQuery(text="recovery"))) == 1
                assert await service.dispose_source("document_version", source_id) == 1
                assert await service.dispose_source("document_version", source_id) == 0
                assert await service.search(SearchQuery(text="recovery")) == ()
        async with sessions() as session:
            async with ExecutionContextService().transaction(session, other_context):
                isolated = SearchContextService(
                    session, other_context, authorizer=AllowAuthorizer()
                )
                assert await isolated.search(SearchQuery(text="recovery")) == ()
        with pytest.raises(Exception):
            _require_migration(name, PREVIOUS, direction="downgrade")
    finally:
        if engine:
            await engine.dispose()
        await _drop_database(admin, name)
        await admin.close()


@pytest.mark.skipif(SOURCE_DATABASE_URL is None, reason="PostgreSQL URL is required")
async def test_h3_06_pgvector_semantic_retrieval() -> None:
    admin, name = await _create_database()
    engine = None
    try:
        _require_migration(name, REVISION)
        from tests.memberships.test_h1_04_postgres import _seed_business_workspace

        organization_id, workspace_id, _, owner_id, _ = await _seed_business_workspace(name)
        context = await _context_for_owner(
            name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            async with ExecutionContextService().transaction(session, context):
                service = SearchContextService(
                    session,
                    context,
                    authorizer=AllowAuthorizer(),
                    embedding=DeterministicEmbedding(),
                )
                generation = await service.create_generation(
                    generation_id=uuid4(),
                    index_version="semantic-v1",
                    chunker_version="source-v1",
                    policy_version=1,
                    manifest_digest="c" * 64,
                )
                expected = await service.index(
                    generation.id,
                    SearchDocumentInput(
                        source_kind="knowledge_claim",
                        source_id=uuid4(),
                        source_version=1,
                        source_digest="d" * 64,
                        title="Semantic source",
                        content="Provider-neutral vector evidence",
                        classification=Classification.CONFIDENTIAL,
                        visibility="workspace",
                        policy_version=1,
                    ),
                )
                await service.activate_generation(generation.id)
                results = await service.search(SearchQuery(text="semantic relationship"))
                assert results[0].id == expected.id
    finally:
        if engine:
            await engine.dispose()
        await _drop_database(admin, name)
        await admin.close()
