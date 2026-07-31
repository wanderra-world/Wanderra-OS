"""Shared contracts for reversible capability routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol, TypeVar


class CapabilityRoute(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    CANONICAL = "canonical"


class AuthorizationGate(Protocol):
    async def require(self, permission: str) -> None: ...


T = TypeVar("T")


class MutationGuard(Protocol):
    async def require_approval(self, approval_id: str) -> None: ...

    async def execute_once(
        self,
        idempotency_key: str,
        request_digest: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T: ...
