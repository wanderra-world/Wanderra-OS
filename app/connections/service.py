"""Authorized transactional service for H2-01 connection state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import (
    AuthorizationRequest,
    AuthorizationService,
    DecisionEffect,
)
from app.connections.contracts import (
    CapabilityGrant,
    ConnectionAuthorizationError,
    ConnectionConcurrencyError,
    ConnectionCreate,
    ConnectionLifecycleError,
    ConnectionRegistryError,
    ConnectionStatus,
    require_transition,
)
from app.connections.models import Connection, ConnectionCapabilityGrant
from app.connections.repository import ConnectionRepository
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent


class ConnectionAuthorizer(Protocol):
    async def authorize(
        self,
        context: ExecutionContext,
        permission_key: str,
    ) -> bool:
        """Return whether H1 grants the requested workspace permission."""


class H1ConnectionAuthorizer:
    """Translate H2 lifecycle authorization into the accepted H1 boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._service = AuthorizationService(session)

    async def authorize(
        self,
        context: ExecutionContext,
        permission_key: str,
    ) -> bool:
        decision = await self._service.authorize(
            AuthorizationRequest(
                actor_id=context.actor.actor_id,
                session_id=context.actor.session_id,
                organization_id=context.tenant.organization_id,
                requested_workspace_id=context.tenant.workspace_id,
                membership_workspace_id=context.tenant.workspace_id,
                membership_id=context.actor.membership_id,
                permission_key=permission_key,
                request_reference=context.request.request_id,
            )
        )
        return decision.effect is DecisionEffect.ALLOW


class ConnectionService:
    """Create and transition connections in the caller-owned transaction."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: ConnectionAuthorizer | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._repository = ConnectionRepository(session, context)
        self._authorizer = authorizer or H1ConnectionAuthorizer(session)
        self._audit = AuditWriterService(session, context)

    async def create(
        self,
        command: ConnectionCreate,
        *,
        now: datetime | None = None,
    ) -> Connection:
        await self._require_authorized()
        await self._validate_registry(command)
        created_at = now or datetime.now(UTC)
        connection = Connection(
            workspace_id=self._context.tenant.workspace_id,
            id=command.connection_id,
            organization_id=self._context.tenant.organization_id,
            cell_id=self._context.tenant.cell_id,
            provider_key=command.provider_key,
            provider_version=1,
            connection_kind=command.connection_kind,
            connection_kind_version=command.connection_kind_version,
            provider_account_id=command.provider_account_id,
            display_name=command.display_name,
            granted_scopes=list(command.granted_scopes),
            status=ConnectionStatus.PENDING.value,
            created_by_user_id=self._context.actor.actor_id,
            last_material_actor_id=self._context.actor.actor_id,
            version=1,
            created_at=created_at,
            updated_at=created_at,
        )
        await self._repository.add(connection)
        for grant in command.capability_grants:
            await self._repository.add_grant(
                ConnectionCapabilityGrant(
                    workspace_id=connection.workspace_id,
                    connection_id=connection.id,
                    connection_kind=connection.connection_kind,
                    connection_kind_version=connection.connection_kind_version,
                    capability_key=grant.capability_key,
                    capability_version=grant.version,
                    status="granted",
                    granted_by_user_id=self._context.actor.actor_id,
                    granted_at=created_at,
                )
            )
        await self._record_material_event(connection, "connection.created")
        return connection

    async def get(self, *, connection_id: uuid.UUID) -> Connection:
        await self._require_authorized(permission_key="read_content")
        return await self._require_connection(connection_id)

    async def list_for_workspace(self) -> list[Connection]:
        await self._require_authorized(permission_key="read_content")
        return await self._repository.list_for_workspace(
            workspace_id=self._context.tenant.workspace_id
        )

    async def transition(
        self,
        *,
        connection_id: uuid.UUID,
        expected_version: int,
        target: ConnectionStatus,
        now: datetime | None = None,
    ) -> Connection:
        await self._require_authorized()
        connection = await self._require_connection(connection_id, for_update=True)
        if connection.version != expected_version:
            raise ConnectionConcurrencyError("connection version precondition failed")
        current = ConnectionStatus(connection.status)
        require_transition(current, target)
        changed_at = now or datetime.now(UTC)
        connection.status = target.value
        connection.version += 1
        connection.last_material_actor_id = self._context.actor.actor_id
        connection.updated_at = changed_at
        if target is ConnectionStatus.ACTIVE:
            connection.activated_at = connection.activated_at or changed_at
            connection.degraded_at = None
            connection.reauthorization_required_at = None
        elif target is ConnectionStatus.DEGRADED:
            connection.degraded_at = changed_at
        elif target is ConnectionStatus.REAUTHORIZATION_REQUIRED:
            connection.reauthorization_required_at = changed_at
        elif target is ConnectionStatus.REVOKED:
            connection.revoked_at = changed_at
        elif target is ConnectionStatus.CLOSED:
            connection.closed_at = changed_at
        await self._record_material_event(
            connection,
            f"connection.{target.value}",
        )
        return connection

    async def grant_capability(
        self,
        *,
        connection_id: uuid.UUID,
        expected_version: int,
        grant: CapabilityGrant,
        now: datetime | None = None,
    ) -> ConnectionCapabilityGrant:
        await self._require_authorized()
        connection = await self._require_connection(connection_id, for_update=True)
        self._require_mutable_connection(connection)
        if connection.version != expected_version:
            raise ConnectionConcurrencyError("connection version precondition failed")
        if not await self._repository.capability_is_allowed(
            kind_key=connection.connection_kind,
            kind_version=connection.connection_kind_version,
            capability_key=grant.capability_key,
            capability_version=grant.version,
        ):
            raise ConnectionRegistryError("connection capability is unknown or inactive")
        changed_at = now or datetime.now(UTC)
        record = await self._repository.get_grant(
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            capability_key=grant.capability_key,
            capability_version=grant.version,
            for_update=True,
        )
        if record is None:
            record = await self._repository.add_grant(
                ConnectionCapabilityGrant(
                    workspace_id=connection.workspace_id,
                    connection_id=connection.id,
                    connection_kind=connection.connection_kind,
                    connection_kind_version=connection.connection_kind_version,
                    capability_key=grant.capability_key,
                    capability_version=grant.version,
                    status="granted",
                    granted_by_user_id=self._context.actor.actor_id,
                    granted_at=changed_at,
                )
            )
        elif record.status == "granted":
            raise ConnectionLifecycleError("connection capability is already granted")
        else:
            record.status = "granted"
            record.granted_by_user_id = self._context.actor.actor_id
            record.granted_at = changed_at
            record.revoked_at = None
        connection.version += 1
        connection.last_material_actor_id = self._context.actor.actor_id
        connection.updated_at = changed_at
        await self._record_material_event(
            connection,
            "connection.capability_granted",
            capability=grant,
        )
        return record

    async def revoke_capability(
        self,
        *,
        connection_id: uuid.UUID,
        expected_version: int,
        grant: CapabilityGrant,
        now: datetime | None = None,
    ) -> ConnectionCapabilityGrant:
        await self._require_authorized()
        connection = await self._require_connection(connection_id, for_update=True)
        self._require_mutable_connection(connection)
        if connection.version != expected_version:
            raise ConnectionConcurrencyError("connection version precondition failed")
        record = await self._repository.get_grant(
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            capability_key=grant.capability_key,
            capability_version=grant.version,
            for_update=True,
        )
        if record is None or record.status != "granted":
            raise ConnectionLifecycleError("connection capability is not granted")
        changed_at = now or datetime.now(UTC)
        record.status = "revoked"
        record.revoked_at = changed_at
        connection.version += 1
        connection.last_material_actor_id = self._context.actor.actor_id
        connection.updated_at = changed_at
        await self._record_material_event(
            connection,
            "connection.capability_revoked",
            capability=grant,
        )
        return record

    async def effective_capabilities(
        self,
        *,
        connection_id: uuid.UUID,
    ) -> tuple[str, ...]:
        await self._require_authorized(permission_key="read_content")
        await self._require_connection(connection_id)
        return await self._repository.effective_capabilities(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=connection_id,
        )

    async def _validate_registry(self, command: ConnectionCreate) -> None:
        if not await self._repository.provider_is_active(command.provider_key):
            raise ConnectionRegistryError("connection provider is unknown or inactive")
        if not await self._repository.kind_is_active(
            command.connection_kind,
            command.connection_kind_version,
        ):
            raise ConnectionRegistryError("connection kind is unknown or inactive")
        for grant in command.capability_grants:
            if not await self._repository.capability_is_allowed(
                kind_key=command.connection_kind,
                kind_version=command.connection_kind_version,
                capability_key=grant.capability_key,
                capability_version=grant.version,
            ):
                raise ConnectionRegistryError(
                    "connection capability is unknown or inactive"
                )

    async def _require_authorized(
        self,
        *,
        permission_key: str = "manage_workspace",
    ) -> None:
        if not await self._authorizer.authorize(
            self._context,
            permission_key,
        ):
            raise ConnectionAuthorizationError(
                "workspace connection administration is denied"
            )

    async def _require_connection(
        self,
        connection_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Connection:
        connection = await self._repository.get(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=connection_id,
            for_update=for_update,
        )
        if connection is None:
            raise ConnectionLifecycleError("connection does not exist")
        return connection

    @staticmethod
    def _require_mutable_connection(connection: Connection) -> None:
        if connection.status in (
            ConnectionStatus.REVOKED.value,
            ConnectionStatus.CLOSED.value,
        ):
            raise ConnectionLifecycleError(
                "revoked or closed connection cannot change capability grants"
            )

    async def _record_material_event(
        self,
        connection: Connection,
        action: str,
        *,
        capability: CapabilityGrant | None = None,
    ) -> None:
        details: dict[str, object] = {
            "connection_id": str(connection.id),
            "provider_key": connection.provider_key,
            "connection_kind": connection.connection_kind,
            "status": connection.status,
            "connection_version": connection.version,
        }
        if capability is not None:
            details["capability_key"] = capability.capability_key
            details["capability_version"] = capability.version
        audit = await self._audit.write(
            AuditInput(
                action=action,
                target_type="connection",
                target_id=connection.id,
                outcome="success",
                details=details,
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=connection.workspace_id,
                id=uuid.uuid4(),
                event_type=action,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="connection",
                aggregate_id=connection.id,
                aggregate_sequence=connection.version,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="internal",
                payload={"audit_event_id": str(audit.id), **details},
            )
        )
        await self._session.flush()
