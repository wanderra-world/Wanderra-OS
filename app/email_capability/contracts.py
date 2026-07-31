"""Contracts for reversible email capability routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol, TypeVar

from app.provider_capabilities.email import EmailMessage, EmailPort


class EmailRoute(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    CANONICAL = "canonical"


class EmailOperation(StrEnum):
    PROFILE = "profile"
    LIST = "list"
    UNREAD = "unread"
    SEARCH = "search"
    DRAFT = "draft"
    SEND = "send"


class AuthorizationGate(Protocol):
    async def require(self, permission: str) -> None: ...


class CanonicalEmailPortFactory(Protocol):
    async def canonical_port(self) -> EmailPort: ...


class EmailResourceObserver(Protocol):
    async def observe(self, message: EmailMessage) -> None: ...


T = TypeVar("T")


class EmailRoutingStore(Protocol):
    async def route(self) -> EmailRoute: ...

    async def record_comparison(
        self, operation: EmailOperation, equivalent: bool
    ) -> None: ...


class MutationGuard(Protocol):
    async def require_approval(self, approval_id: str) -> None: ...

    async def execute_once(
        self,
        idempotency_key: str,
        request_digest: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T: ...
