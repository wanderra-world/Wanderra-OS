"""Authorized, provider-neutral integration resolution without adapter execution."""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.connection_credentials.models import ConnectionCredential
from app.connections.models import Connection
from app.connections.service import ConnectionAuthorizer, H1ConnectionAuthorizer
from app.execution_context import ExecutionContext
from app.integration_layer.contracts import (
    IntegrationAuthorizationError,
    IntegrationCapabilityError,
    IntegrationCredentialError,
    IntegrationResolution,
    IntegrationResolutionRequest,
    IntegrationStateError,
)
from app.integration_layer.repository import IntegrationRepository
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.provider_capabilities.common import CapabilityRegistry, ProviderCapabilityError


class IntegrationRepositoryPort(Protocol):
    async def get_connection(self, connection_id: uuid.UUID) -> Connection | None: ...

    async def provider_is_active(self, provider_key: str, version: int) -> bool: ...

    async def capability_is_granted(
        self,
        connection_id: uuid.UUID,
        capability_key: str,
        capability_version: int,
    ) -> bool: ...

    async def latest_credential(
        self,
        connection_id: uuid.UUID,
        credential_kind: str,
    ) -> ConnectionCredential | None: ...


class IntegrationAuditPort(Protocol):
    async def write(self, audit: AuditInput) -> object: ...


class IntegrationResolver:
    """Resolve one authorized integration operation into inert, non-secret metadata."""

    def __init__(
        self,
        context: ExecutionContext,
        *,
        repository: IntegrationRepositoryPort,
        capability_registry: CapabilityRegistry,
        authorizer: ConnectionAuthorizer,
        audit: IntegrationAuditPort,
    ) -> None:
        self.context = context
        self._repository = repository
        self._capabilities = capability_registry
        self._authorizer = authorizer
        self._audit = audit

    @classmethod
    def for_session(
        cls,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        capability_registry: CapabilityRegistry,
        authorizer: ConnectionAuthorizer | None = None,
    ) -> IntegrationResolver:
        return cls(
            context,
            repository=IntegrationRepository(session, context),
            capability_registry=capability_registry,
            authorizer=authorizer or H1ConnectionAuthorizer(session),
            audit=AuditWriterService(session, context),
        )

    async def resolve(
        self,
        request: IntegrationResolutionRequest,
    ) -> IntegrationResolution:
        if not await self._authorizer.authorize(self.context, request.permission_key):
            raise IntegrationAuthorizationError("integration resolution is denied")

        connection = await self._repository.get_connection(request.connection_id)
        if connection is None or connection.workspace_id != self.context.tenant.workspace_id:
            raise IntegrationStateError("workspace integration is unavailable")
        if connection.status != "active":
            raise IntegrationStateError("workspace integration is not active")
        if not await self._repository.provider_is_active(
            connection.provider_key,
            connection.provider_version,
        ):
            raise IntegrationStateError("integration provider is unavailable")

        if not await self._repository.capability_is_granted(
            connection.id,
            request.capability_key,
            request.capability_version,
        ):
            raise IntegrationCapabilityError("integration capability is not granted")
        try:
            descriptor = self._capabilities.discover(
                connection.provider_key,
                request.capability_key,
            )
        except ProviderCapabilityError as error:
            raise IntegrationCapabilityError(
                "integration capability is not registered"
            ) from error
        if descriptor.version != request.capability_version:
            raise IntegrationCapabilityError("integration capability version is unsupported")
        if request.operation not in descriptor.operations:
            raise IntegrationCapabilityError("integration operation is unsupported")

        credential = await self._repository.latest_credential(
            connection.id,
            request.credential_kind,
        )
        if credential is None:
            raise IntegrationCredentialError("integration authorization is unavailable")
        if (
            credential.connection_id != connection.id
            or credential.provider_key != connection.provider_key
        ):
            raise IntegrationCredentialError("integration authorization does not match")
        if credential.status not in {"active", "shadow_verified"}:
            raise IntegrationCredentialError("integration authorization is unavailable")
        if not set(request.required_scopes).issubset(credential.scopes):
            raise IntegrationCredentialError("integration authorization scope is insufficient")

        await self._audit.write(
            AuditInput(
                action="integration.resolved",
                target_type="connection",
                target_id=connection.id,
                outcome="success",
                details={
                    "provider_key": connection.provider_key,
                    "capability_key": request.capability_key,
                    "capability_version": request.capability_version,
                    "operation": request.operation,
                    "auth_generation": credential.generation,
                },
            )
        )
        return IntegrationResolution(
            organization_id=self.context.tenant.organization_id,
            workspace_id=self.context.tenant.workspace_id,
            connection_id=connection.id,
            provider_key=connection.provider_key,
            provider_account_id=connection.provider_account_id,
            capability_key=request.capability_key,
            capability_version=request.capability_version,
            operation=request.operation,
            credential_id=credential.id,
            credential_kind=credential.credential_kind,
            credential_generation=credential.generation,
            authorization_decision_id=self.context.actor.authorization_decision_id,
            correlation_id=self.context.request.correlation_id,
        )
