"""Contracts for reversible Calendar capability routing."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from app.capability_routing.contracts import CapabilityRoute
from app.provider_capabilities.calendar import CalendarEvent, CalendarPort

CalendarRoute = CapabilityRoute


class CalendarOperation(StrEnum):
    LIST = "list"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class CanonicalCalendarPortFactory(Protocol):
    async def canonical_port(self) -> CalendarPort: ...


class CalendarRoutingStore(Protocol):
    async def route(self) -> CalendarRoute: ...

    async def record_comparison(
        self, operation: CalendarOperation, equivalent: bool
    ) -> None: ...


class CalendarResourceObserver(Protocol):
    async def observe(self, event: CalendarEvent) -> None: ...
