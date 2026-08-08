from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.execution_context import ActorContext, ExecutionContext, RequestContext, TenantContext
from app.integration_layer import (
    IntegrationAuthorizationError,
    IntegrationCapabilityError,
    IntegrationCredentialError,
    IntegrationResolutionRequest,
    IntegrationResolver,
    IntegrationStateError,
)
from app.provider_capabilities.common import CapabilityDescriptor, CapabilityRegistry


@dataclass(frozen=True)
class ConnectionView:
    workspace_id: uuid.UUID
    id: uuid.UUID
    provider_key: str
    provider_version: int
    provider_account_id: str
    status: str


@dataclass(frozen=True)
class CredentialView:
    id: uuid.UUID
    connection_id: uuid.UUID
    provider_key: str
    credential_kind: str
    generation: int
    status: str
    scopes: tuple[str, ...]


class FakeRepository:
    def __init__(self, connection: ConnectionView, credential: CredentialView | None) -> None:
        self.connection = connection
        self.credential = credential
        self.granted = True
        self.provider_active = True

    async def get_connection(self, connection_id: uuid.UUID) -> ConnectionView | None:
        return self.connection if connection_id == self.connection.id else None

    async def provider_is_active(self, provider_key: str, version: int) -> bool:
        return (
            self.provider_active
            and provider_key == self.connection.provider_key
            and version == self.connection.provider_version
        )

    async def capability_is_granted(
        self, connection_id: uuid.UUID, capability_key: str, capability_version: int
    ) -> bool:
        return self.granted and connection_id == self.connection.id

    async def latest_credential(
        self, connection_id: uuid.UUID, credential_kind: str
    ) -> CredentialView | None:
        if self.credential is None:
            return None
        if (
            connection_id != self.credential.connection_id
            or credential_kind != self.credential.credential_kind
        ):
            return None
        return self.credential


class FakeAuthorizer:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    async def authorize(
        self, context: ExecutionContext, permission_key: str
    ) -> bool:
        return self.allowed


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[object] = []

    async def write(self, audit: object) -> object:
        self.records.append(audit)
        return object()


def context() -> ExecutionContext:
    return ExecutionContext(
        request=RequestContext(request_id="request-1", correlation_id="correlation-1"),
        actor=ActorContext(
            actor_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            membership_id=uuid.uuid4(),
            authorization_decision_id=uuid.uuid4(),
        ),
        tenant=TenantContext(
            organization_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            cell_id=uuid.uuid4(),
        ),
    )


def resolver(
    *,
    allowed: bool = True,
    status: str = "active",
    credential_status: str = "active",
) -> tuple[IntegrationResolver, IntegrationResolutionRequest, FakeAudit, FakeRepository]:
    execution = context()
    connection_id = uuid.uuid4()
    connection = ConnectionView(
        workspace_id=execution.tenant.workspace_id,
        id=connection_id,
        provider_key="synthetic_provider",
        provider_version=1,
        provider_account_id="account-1",
        status=status,
    )
    credential = CredentialView(
        id=uuid.uuid4(),
        connection_id=connection_id,
        provider_key="synthetic_provider",
        credential_kind="oauth_refresh",
        generation=2,
        status=credential_status,
        scopes=("mail.read", "profile.read"),
    )
    repository = FakeRepository(connection, credential)
    registry = CapabilityRegistry()
    registry.register(
        "synthetic_provider",
        (CapabilityDescriptor("email.read", 1, ("list", "get")),),
    )
    audit = FakeAudit()
    service = IntegrationResolver(
        execution,
        repository=repository,
        capability_registry=registry,
        authorizer=FakeAuthorizer(allowed),
        audit=audit,
    )
    request = IntegrationResolutionRequest(
        connection_id=connection_id,
        capability_key="email.read",
        capability_version=1,
        operation="list",
        permission_key="read_content",
        credential_kind="oauth_refresh",
        required_scopes=("mail.read",),
    )
    return service, request, audit, repository


@pytest.mark.asyncio
async def test_resolve_returns_workspace_owned_inert_metadata_and_audits() -> None:
    service, request, audit, _ = resolver()

    result = await service.resolve(request)

    assert result.workspace_id == service.context.tenant.workspace_id
    assert result.provider_key == "synthetic_provider"
    assert result.provider_account_id == "account-1"
    assert result.capability_key == "email.read"
    assert result.operation == "list"
    assert result.credential_generation == 2
    assert result.correlation_id == "correlation-1"
    assert len(audit.records) == 1
    assert "token" not in repr(result).casefold()


@pytest.mark.asyncio
async def test_missing_authorization_fails_before_repository_resolution() -> None:
    service, request, audit, repository = resolver(allowed=False)
    repository.connection = None  # type: ignore[assignment]

    with pytest.raises(IntegrationAuthorizationError):
        await service.resolve(request)
    assert audit.records == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["pending", "degraded", "reauthorization_required", "revoked", "closed"]
)
async def test_unusable_connection_status_fails_closed(status: str) -> None:
    service, request, audit, _ = resolver(status=status)
    with pytest.raises(IntegrationStateError):
        await service.resolve(request)
    assert audit.records == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["reauthorization_required", "revoked", "disabled"])
async def test_unusable_credential_status_fails_closed(status: str) -> None:
    service, request, audit, _ = resolver(credential_status=status)
    with pytest.raises(IntegrationCredentialError):
        await service.resolve(request)
    assert audit.records == []


@pytest.mark.asyncio
async def test_capability_grant_operation_and_scope_are_enforced() -> None:
    service, request, audit, repository = resolver()
    repository.granted = False
    with pytest.raises(IntegrationCapabilityError):
        await service.resolve(request)

    service, request, _, _ = resolver()
    invalid_operation = IntegrationResolutionRequest(
        connection_id=request.connection_id,
        capability_key=request.capability_key,
        capability_version=request.capability_version,
        operation="delete",
        permission_key=request.permission_key,
        credential_kind=request.credential_kind,
        required_scopes=request.required_scopes,
    )
    with pytest.raises(IntegrationCapabilityError):
        await service.resolve(invalid_operation)

    service, request, _, _ = resolver()
    missing_scope = IntegrationResolutionRequest(
        connection_id=request.connection_id,
        capability_key=request.capability_key,
        capability_version=request.capability_version,
        operation=request.operation,
        permission_key=request.permission_key,
        credential_kind=request.credential_kind,
        required_scopes=("mail.send",),
    )
    with pytest.raises(IntegrationCredentialError):
        await service.resolve(missing_scope)
    assert audit.records == []


@pytest.mark.asyncio
async def test_inactive_provider_and_mismatched_credential_fail_closed() -> None:
    service, request, audit, repository = resolver()
    repository.provider_active = False
    with pytest.raises(IntegrationStateError, match="provider"):
        await service.resolve(request)

    service, request, audit, repository = resolver()
    assert repository.credential is not None
    repository.credential = CredentialView(
        id=repository.credential.id,
        connection_id=repository.credential.connection_id,
        provider_key="different_provider",
        credential_kind=repository.credential.credential_kind,
        generation=repository.credential.generation,
        status=repository.credential.status,
        scopes=repository.credential.scopes,
    )
    with pytest.raises(IntegrationCredentialError, match="match"):
        await service.resolve(request)
    assert audit.records == []
