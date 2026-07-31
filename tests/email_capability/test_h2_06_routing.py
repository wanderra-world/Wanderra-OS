from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.email_capability.contracts import EmailOperation, EmailRoute
from app.email_capability.service import EmailCapabilityService
from app.provider_capabilities.common import MutationContext
from app.provider_capabilities.email import (
    EmailAddress,
    EmailMessage,
    EmailMessageCreate,
    EmailProfile,
)


@dataclass
class Port:
    address: str
    calls: int = 0

    async def profile(self) -> EmailProfile:
        self.calls += 1
        return EmailProfile(self.address)

    async def send_message(
        self, message: EmailMessageCreate, context: MutationContext
    ) -> EmailMessage:
        self.calls += 1
        return EmailMessage(
            "sent-1",
            None,
            sender=EmailAddress("atlas@example.com"),
            recipients=(),
            subject=message.subject,
            body_text=message.body_text,
        )


class Gate:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[str] = []

    async def require(self, permission: str) -> None:
        self.calls.append(permission)
        if not self.allowed:
            raise PermissionError("denied")


class Store:
    def __init__(self, route: EmailRoute) -> None:
        self.selected_route = route
        self.comparisons: list[bool] = []

    async def route(self) -> EmailRoute:
        return self.selected_route

    async def record_comparison(
        self, operation: EmailOperation, equivalent: bool
    ) -> None:
        self.comparisons.append(equivalent)


class Factory:
    def __init__(self, port: Port) -> None:
        self.port = port
        self.calls = 0

    async def canonical_port(self) -> Port:
        self.calls += 1
        return self.port


class Mutations:
    def __init__(self) -> None:
        self.approvals: list[str] = []
        self.results: dict[str, tuple[str, object]] = {}

    async def require_approval(self, approval_id: str) -> None:
        self.approvals.append(approval_id)

    async def execute_once(self, key: str, digest: str, operation):
        prior = self.results.get(key)
        if prior:
            if prior[0] != digest:
                raise RuntimeError("changed replay")
            return prior[1]
        result = await operation()
        self.results[key] = (digest, result)
        return result


@pytest.mark.asyncio
async def test_shadow_returns_legacy_and_records_equivalence() -> None:
    legacy, canonical = Port("atlas@example.com"), Port("atlas@example.com")
    store, gate, factory = Store(EmailRoute.SHADOW), Gate(), Factory(canonical)
    service = EmailCapabilityService(legacy, factory, store, gate)

    assert (await service.profile()).email_address == "atlas@example.com"
    assert legacy.calls == canonical.calls == 1
    assert store.comparisons == [True]
    assert gate.calls == ["read_content"]


@pytest.mark.asyncio
async def test_legacy_route_never_opens_managed_credentials_or_provider() -> None:
    legacy, canonical = Port("legacy@example.com"), Port("new@example.com")
    service = EmailCapabilityService(
        legacy, Factory(canonical), Store(EmailRoute.LEGACY), Gate()
    )
    assert (await service.profile()).email_address == "legacy@example.com"
    assert canonical.calls == 0


@pytest.mark.asyncio
async def test_denial_precedes_route_credential_and_provider_access() -> None:
    factory = Factory(Port("new@example.com"))
    service = EmailCapabilityService(
        Port("legacy@example.com"), factory, Store(EmailRoute.CANONICAL), Gate(False)
    )
    with pytest.raises(PermissionError):
        await service.profile()
    assert factory.calls == 0


@pytest.mark.asyncio
async def test_send_requires_approval_and_is_idempotent_without_dual_write() -> None:
    port, mutations = Port("atlas@example.com"), Mutations()
    service = EmailCapabilityService(
        port,
        Factory(Port("canonical@example.com")),
        Store(EmailRoute.LEGACY),
        Gate(),
        mutations,
    )
    message = EmailMessageCreate(
        to=("user@example.com",), subject="Atlas", body_text="Working"
    )
    first = await service.send_message(
        message, MutationContext("send-1"), approval_id="approval-1"
    )
    second = await service.send_message(
        message, MutationContext("send-1"), approval_id="approval-1"
    )
    assert first == second
    assert port.calls == 1
    assert mutations.approvals == ["approval-1", "approval-1"]
