"""Adversarial PostgreSQL validation for H0-01 tenant isolation."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from tests.architecture.tenancy_prototype import (
    TenancyPrototype,
    assume_runtime_role,
    drop_prototype,
    install_prototype,
    set_workspace_context,
)

TEST_DATABASE_ENV = "H0_TEST_DATABASE_URL"


def _test_database_url() -> str | None:
    """Resolve an asyncpg-compatible URL without exposing credentials."""

    database_url = os.getenv(TEST_DATABASE_ENV) or os.getenv("DATABASE_URL")
    if database_url is None:
        return None
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest_asyncio.fixture
async def postgres_pool() -> AsyncIterator[asyncpg.Pool]:
    database_url = _test_database_url()
    if database_url is None:
        pytest.skip(
            f"{TEST_DATABASE_ENV} or DATABASE_URL is required for PostgreSQL architecture tests"
        )

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=1)
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def tenancy_prototype(
    postgres_pool: asyncpg.Pool,
) -> AsyncIterator[TenancyPrototype]:
    prototype = TenancyPrototype.unique()
    async with postgres_pool.acquire() as connection:
        await install_prototype(connection, prototype)
    try:
        yield prototype
    finally:
        async with postgres_pool.acquire() as connection:
            await drop_prototype(connection, prototype)


@pytest.mark.asyncio
async def test_fit_tenant_001_missing_context_denies_access(
    postgres_pool: asyncpg.Pool,
    tenancy_prototype: TenancyPrototype,
) -> None:
    """FIT-TENANT-001 denies tenant reads and writes without workspace context."""

    async with postgres_pool.acquire() as connection:
        async with connection.transaction():
            await assume_runtime_role(connection, tenancy_prototype)
            count = await connection.fetchval(
                f"SELECT count(*) FROM {tenancy_prototype.schema}.projects"
            )
            assert count == 0

            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    f"""
                    INSERT INTO {tenancy_prototype.schema}.projects
                        (workspace_id, id, name)
                    VALUES ($1, $2, 'Unauthorized')
                    """,
                    tenancy_prototype.workspace_a,
                    uuid4(),
                )


@pytest.mark.asyncio
async def test_fit_tenant_002_workspace_context_filters_rows(
    postgres_pool: asyncpg.Pool,
    tenancy_prototype: TenancyPrototype,
) -> None:
    """FIT-TENANT-002 prevents cross-workspace reads through forced RLS."""

    async with postgres_pool.acquire() as connection:
        async with connection.transaction():
            await assume_runtime_role(connection, tenancy_prototype)
            await set_workspace_context(connection, tenancy_prototype.workspace_a)
            visible = await connection.fetchval(
                f"SELECT count(*) FROM {tenancy_prototype.schema}.projects"
            )
            assert visible == 1

        async with connection.transaction():
            await assume_runtime_role(connection, tenancy_prototype)
            await set_workspace_context(connection, tenancy_prototype.workspace_b)
            visible = await connection.fetchval(
                f"SELECT count(*) FROM {tenancy_prototype.schema}.projects"
            )
            assert visible == 0


@pytest.mark.asyncio
async def test_fit_tenant_003_composite_fk_blocks_cross_workspace_reference(
    postgres_pool: asyncpg.Pool,
    tenancy_prototype: TenancyPrototype,
) -> None:
    """FIT-TENANT-003 rejects references to another workspace's aggregate."""

    async with postgres_pool.acquire() as connection:
        async with connection.transaction():
            await assume_runtime_role(connection, tenancy_prototype)
            await set_workspace_context(connection, tenancy_prototype.workspace_b)

            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await connection.execute(
                    f"""
                    INSERT INTO {tenancy_prototype.schema}.tasks
                        (workspace_id, id, project_id, title)
                    VALUES ($1, $2, $3, 'Cross-workspace task')
                    """,
                    tenancy_prototype.workspace_b,
                    uuid4(),
                    tenancy_prototype.project_a,
                )


@pytest.mark.asyncio
async def test_fit_tenant_004_pool_reuse_does_not_leak_workspace_context(
    postgres_pool: asyncpg.Pool,
    tenancy_prototype: TenancyPrototype,
) -> None:
    """FIT-TENANT-004 proves transaction-local context is cleared on pool reuse."""

    async with postgres_pool.acquire() as connection:
        backend_pid = await connection.fetchval("SELECT pg_backend_pid()")
        async with connection.transaction():
            await assume_runtime_role(connection, tenancy_prototype)
            await set_workspace_context(connection, tenancy_prototype.workspace_a)
            assert (
                await connection.fetchval(
                    f"SELECT count(*) FROM {tenancy_prototype.schema}.projects"
                )
                == 1
            )

    async with postgres_pool.acquire() as reused_connection:
        assert await reused_connection.fetchval("SELECT pg_backend_pid()") == backend_pid
        async with reused_connection.transaction():
            await assume_runtime_role(reused_connection, tenancy_prototype)
            leaked_context = await reused_connection.fetchval(
                "SELECT NULLIF(current_setting('atlas.workspace_id', TRUE), '')"
            )
            visible = await reused_connection.fetchval(
                f"SELECT count(*) FROM {tenancy_prototype.schema}.projects"
            )

            assert leaked_context is None
            assert visible == 0
