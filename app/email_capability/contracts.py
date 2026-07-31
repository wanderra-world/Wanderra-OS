"""Contracts for reversible email capability routing."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from app.capability_routing.contracts import CapabilityRoute
from app.provider_capabilities.email import EmailMessage, EmailPort

EmailRoute = CapabilityRoute


class EmailOperation(StrEnum):
    PROFILE = "profile"
    LIST = "list"
    UNREAD = "unread"
    SEARCH = "search"
    DRAFT = "draft"
    SEND = "send"


class CanonicalEmailPortFactory(Protocol):
    async def canonical_port(self) -> EmailPort: ...


class EmailResourceObserver(Protocol):
    async def observe(self, message: EmailMessage) -> None: ...


class EmailRoutingStore(Protocol):
    async def route(self) -> EmailRoute: ...

    async def mutation_route(self) -> EmailRoute: ...

    async def record_comparison(self, operation: EmailOperation, equivalent: bool) -> None: ...
