"""Read-only composition over canonical H2 connection and credential repositories."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.connection_credentials.models import ConnectionCredential
from app.connection_credentials.repository import ConnectionCredentialRepository
from app.connections.models import Connection
from app.connections.repository import ConnectionRepository
from app.execution_context import ExecutionContext


class IntegrationRepository:
    """Compose existing H2 persistence without owning parallel models."""

    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        self._context = context
        self._connections = ConnectionRepository(session, context)
        self._credentials = ConnectionCredentialRepository(session, context)

    async def get_connection(self, connection_id: uuid.UUID) -> Connection | None:
        return await self._connections.get(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=connection_id,
        )

    async def provider_is_active(self, provider_key: str, version: int) -> bool:
        return await self._connections.provider_is_active(provider_key, version)

    async def capability_is_granted(
        self,
        connection_id: uuid.UUID,
        capability_key: str,
        capability_version: int,
    ) -> bool:
        grant = await self._connections.get_grant(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=connection_id,
            capability_key=capability_key,
            capability_version=capability_version,
        )
        return (
            grant is not None
            and grant.status == "granted"
            and await self._connections.capability_is_allowed(
                kind_key=grant.connection_kind,
                kind_version=grant.connection_kind_version,
                capability_key=grant.capability_key,
                capability_version=grant.capability_version,
            )
        )

    async def latest_credential(
        self,
        connection_id: uuid.UUID,
        credential_kind: str,
    ) -> ConnectionCredential | None:
        return await self._credentials.latest_generation(
            connection_id,
            credential_kind,
        )
