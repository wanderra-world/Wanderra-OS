from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.calendar_capability.contracts import CalendarOperation, CalendarRoute
from app.calendar_capability.service import CalendarCapabilityService
from app.provider_capabilities.calendar import (
    CalendarEvent,
    CalendarEventCreate,
    CalendarListRequest,
    CalendarMoment,
)
from app.provider_capabilities.common import (
    MutationContext,
    Page,
    VersionPrecondition,
)


def event(summary: str) -> CalendarEvent:
    start = datetime(2026, 8, 1, 13, tzinfo=UTC)
    return CalendarEvent(
        "event-1",
        "primary",
        "confirmed",
        summary,
        CalendarMoment(date_time=start),
        CalendarMoment(date_time=start),
        '"v1"',
    )


class Port:
    def __init__(self, summary: str) -> None:
        self.value = event(summary)
        self.calls: list[str] = []

    async def list_events(self, request: CalendarListRequest):
        self.calls.append("list")
        return Page((self.value,))

    async def create_event(self, value, context):
        self.calls.append("create")
        return self.value

    async def update_event(self, external_id, changes, context):
        self.calls.append("update")
        return self.value

    async def delete_event(self, external_id, context):
        self.calls.append("delete")


class Gate:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[str] = []

    async def require(self, permission: str) -> None:
        self.calls.append(permission)
        if not self.allowed:
            raise PermissionError("denied")


class Store:
    def __init__(self, route: CalendarRoute) -> None:
        self.selected = route
        self.comparisons: list[bool] = []

    async def route(self) -> CalendarRoute:
        return self.selected

    async def record_comparison(
        self, operation: CalendarOperation, equivalent: bool
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
        self.outcomes: dict[str, tuple[str, object]] = {}

    async def require_approval(self, approval_id: str) -> None:
        self.approvals.append(approval_id)

    async def execute_once(self, key: str, digest: str, operation):
        if key in self.outcomes:
            prior_digest, result = self.outcomes[key]
            if prior_digest != digest:
                raise RuntimeError("changed replay")
            return result
        result = await operation()
        self.outcomes[key] = (digest, result)
        return result


@pytest.mark.asyncio
async def test_shadow_returns_legacy_and_records_comparison() -> None:
    legacy, canonical = Port("Atlas"), Port("Atlas")
    store = Store(CalendarRoute.SHADOW)
    service = CalendarCapabilityService(
        legacy, Factory(canonical), store, Gate(), Mutations()
    )
    result = await service.list_events(CalendarListRequest())
    assert result.items[0].summary == "Atlas"
    assert legacy.calls == canonical.calls == ["list"]
    assert store.comparisons == [True]


@pytest.mark.asyncio
async def test_legacy_rollback_never_opens_managed_provider() -> None:
    factory = Factory(Port("Canonical"))
    service = CalendarCapabilityService(
        Port("Legacy"),
        factory,
        Store(CalendarRoute.LEGACY),
        Gate(),
        Mutations(),
    )
    assert (await service.list_events(CalendarListRequest())).items[0].summary == "Legacy"
    assert factory.calls == 0


@pytest.mark.asyncio
async def test_denial_precedes_routing_credential_and_provider_access() -> None:
    factory = Factory(Port("Canonical"))
    service = CalendarCapabilityService(
        Port("Legacy"),
        factory,
        Store(CalendarRoute.CANONICAL),
        Gate(False),
        Mutations(),
    )
    with pytest.raises(PermissionError):
        await service.list_events(CalendarListRequest())
    assert factory.calls == 0


@pytest.mark.asyncio
async def test_mutations_require_approval_precondition_and_execute_once() -> None:
    port, mutations = Port("Atlas"), Mutations()
    service = CalendarCapabilityService(
        port,
        Factory(Port("Canonical")),
        Store(CalendarRoute.LEGACY),
        Gate(),
        mutations,
    )
    create = CalendarEventCreate(
        "primary",
        "Atlas",
        datetime(2026, 8, 1, 13, tzinfo=UTC),
        datetime(2026, 8, 1, 14, tzinfo=UTC),
    )
    first = await service.create_event(
        create, MutationContext("create-1"), approval_id="approval-1"
    )
    second = await service.create_event(
        create, MutationContext("create-1"), approval_id="approval-1"
    )
    assert first == second
    assert port.calls == ["create"]

    with pytest.raises(ValueError, match="version precondition"):
        await service.delete_event(
            "event-1",
            MutationContext("delete-1"),
            approval_id="approval-2",
        )

    await service.delete_event(
        "event-1",
        MutationContext(
            "delete-1", VersionPrecondition(etag='"v1"')
        ),
        approval_id="approval-2",
    )
    assert port.calls == ["create", "delete"]
