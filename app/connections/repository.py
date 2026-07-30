"""Context-bound repository for H2-01 connection state."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.models import (
    Connection,
    ConnectionCapabilityGrant,
    ConnectionKind,
    ConnectionKindCapability,
    ProviderCapability,
    ProviderRegistryEntry,
)
from app.execution_context import ContextBoundRepository, ExecutionContext


class ConnectionRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, connection: Connection) -> Connection:
        self.require_workspace(connection.workspace_id)
        self.session.add(connection)
        await self.session.flush()
        return connection

    async def get(
        self,
        *,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
        for_update: bool = False,
    ) -> Connection | None:
        self.require_workspace(workspace_id)
        statement = select(Connection).where(
            Connection.workspace_id == workspace_id,
            Connection.id == connection_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_for_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
    ) -> list[Connection]:
        self.require_workspace(workspace_id)
        rows = await self.session.scalars(
            select(Connection)
            .where(Connection.workspace_id == workspace_id)
            .order_by(Connection.created_at, Connection.id)
        )
        return list(rows)

    async def provider_is_active(self, provider_key: str, version: int = 1) -> bool:
        provider = await self.session.get(
            ProviderRegistryEntry,
            (provider_key, version),
        )
        return provider is not None and provider.active

    async def kind_is_active(self, kind_key: str, version: int) -> bool:
        kind = await self.session.get(ConnectionKind, (kind_key, version))
        return kind is not None and kind.active

    async def capability_is_allowed(
        self,
        *,
        kind_key: str,
        kind_version: int,
        capability_key: str,
        capability_version: int,
    ) -> bool:
        capability = await self.session.get(
            ProviderCapability,
            (capability_key, capability_version),
        )
        if capability is None or not capability.active:
            return False
        allowed = await self.session.get(
            ConnectionKindCapability,
            (
                kind_key,
                kind_version,
                capability_key,
                capability_version,
            ),
        )
        return allowed is not None

    async def add_grant(
        self,
        grant: ConnectionCapabilityGrant,
    ) -> ConnectionCapabilityGrant:
        self.require_workspace(grant.workspace_id)
        self.session.add(grant)
        await self.session.flush()
        return grant

    async def get_grant(
        self,
        *,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
        capability_key: str,
        capability_version: int,
        for_update: bool = False,
    ) -> ConnectionCapabilityGrant | None:
        self.require_workspace(workspace_id)
        statement = select(ConnectionCapabilityGrant).where(
            ConnectionCapabilityGrant.workspace_id == workspace_id,
            ConnectionCapabilityGrant.connection_id == connection_id,
            ConnectionCapabilityGrant.capability_key == capability_key,
            ConnectionCapabilityGrant.capability_version == capability_version,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def effective_capabilities(
        self,
        *,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> tuple[str, ...]:
        self.require_workspace(workspace_id)
        rows = await self.session.scalars(
            select(ConnectionCapabilityGrant.capability_key)
            .join(
                Connection,
                (
                    Connection.workspace_id
                    == ConnectionCapabilityGrant.workspace_id
                )
                & (Connection.id == ConnectionCapabilityGrant.connection_id),
            )
            .where(
                ConnectionCapabilityGrant.workspace_id == workspace_id,
                ConnectionCapabilityGrant.connection_id == connection_id,
                ConnectionCapabilityGrant.status == "granted",
                Connection.status.in_(("active", "degraded")),
            )
            .order_by(ConnectionCapabilityGrant.capability_key)
        )
        return tuple(rows)
