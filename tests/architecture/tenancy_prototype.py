"""Disposable PostgreSQL tenancy prototype used only by H0 architecture tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

SQL_TEMPLATE = Path(__file__).with_name("sql").joinpath("tenancy_prototype.sql")
SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class TenancyPrototype:
    """Names and seed identities for one isolated disposable prototype."""

    schema: str
    runtime_role: str
    workspace_a: UUID
    workspace_b: UUID
    project_a: UUID

    @classmethod
    def unique(cls) -> TenancyPrototype:
        suffix = uuid4().hex[:12]
        return cls(
            schema=f"h0_tenant_{suffix}",
            runtime_role=f"h0_runtime_{suffix}",
            workspace_a=uuid4(),
            workspace_b=uuid4(),
            project_a=uuid4(),
        )


def render_prototype_sql(prototype: TenancyPrototype) -> str:
    """Render the reviewed SQL template using generated safe identifiers."""

    identifiers = {
        "{{SCHEMA}}": prototype.schema,
        "{{RUNTIME_ROLE}}": prototype.runtime_role,
    }
    for identifier in identifiers.values():
        if SAFE_IDENTIFIER.fullmatch(identifier) is None:
            raise ValueError(f"unsafe PostgreSQL identifier: {identifier!r}")

    sql = SQL_TEMPLATE.read_text(encoding="utf-8")
    for placeholder, identifier in identifiers.items():
        sql = sql.replace(placeholder, identifier)
    return sql


async def install_prototype(
    connection: asyncpg.Connection,
    prototype: TenancyPrototype,
) -> None:
    """Install and seed a disposable tenancy prototype."""

    await connection.execute(render_prototype_sql(prototype))
    await connection.executemany(
        f"INSERT INTO {prototype.schema}.workspaces (id, cell_id) VALUES ($1, $2)",
        (
            (prototype.workspace_a, "primary"),
            (prototype.workspace_b, "primary"),
        ),
    )
    await connection.execute(
        f"""
        INSERT INTO {prototype.schema}.projects (workspace_id, id, name)
        VALUES ($1, $2, 'Workspace A project')
        """,
        prototype.workspace_a,
        prototype.project_a,
    )


async def drop_prototype(
    connection: asyncpg.Connection,
    prototype: TenancyPrototype,
) -> None:
    """Remove all disposable objects created by ``install_prototype``."""

    await connection.execute("RESET ROLE")
    await connection.execute(f"DROP SCHEMA IF EXISTS {prototype.schema} CASCADE")
    await connection.execute(f"DROP ROLE IF EXISTS {prototype.runtime_role}")


async def assume_runtime_role(
    connection: asyncpg.Connection,
    prototype: TenancyPrototype,
) -> None:
    """Assume the non-bypass runtime role for the current transaction."""

    await connection.execute(f"SET LOCAL ROLE {prototype.runtime_role}")


async def set_workspace_context(
    connection: asyncpg.Connection,
    workspace_id: UUID,
) -> None:
    """Set workspace context transaction-locally and never at connection scope."""

    await connection.execute(
        "SELECT set_config('atlas.workspace_id', $1, TRUE)",
        str(workspace_id),
    )
