"""Versioned input and output contracts for fixed-role authorization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

AUTHORIZATION_POLICY_VERSION = "h1-05-v1"
PERMISSION_DEFINITION_VERSION = 1


class DecisionEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class ReasonCode(StrEnum):
    ALLOWED = "allowed"
    INVALID_ACTOR = "invalid_actor"
    INVALID_SESSION = "invalid_session"
    INVALID_MEMBERSHIP = "invalid_membership"
    WORKSPACE_MISMATCH = "workspace_mismatch"
    UNKNOWN_PERMISSION = "unknown_permission"
    EXPLICIT_DENY = "explicit_deny"
    ROLE_PERMISSION_MISSING = "role_permission_missing"


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """Complete H1-05 fixed-role lookup input."""

    actor_id: uuid.UUID
    session_id: uuid.UUID
    organization_id: uuid.UUID
    requested_workspace_id: uuid.UUID
    membership_workspace_id: uuid.UUID
    membership_id: uuid.UUID
    permission_key: str
    permission_version: int = PERMISSION_DEFINITION_VERSION
    request_reference: str = "request"

    def __post_init__(self) -> None:
        if not self.permission_key.strip():
            raise ValueError("permission key is required")
        if self.permission_version < 1:
            raise ValueError("permission version must be positive")
        if not self.request_reference.strip():
            raise ValueError("request reference is required")


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    effect: DecisionEffect
    reason: ReasonCode
    policy_version: str
    permission_version: int
    decided_at: datetime

    @classmethod
    def allow(
        cls,
        permission_version: int,
        *,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        return cls(
            effect=DecisionEffect.ALLOW,
            reason=ReasonCode.ALLOWED,
            policy_version=AUTHORIZATION_POLICY_VERSION,
            permission_version=permission_version,
            decided_at=now or datetime.now(UTC),
        )

    @classmethod
    def deny(
        cls,
        reason: ReasonCode,
        permission_version: int,
        *,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        return cls(
            effect=DecisionEffect.DENY,
            reason=reason,
            policy_version=AUTHORIZATION_POLICY_VERSION,
            permission_version=permission_version,
            decided_at=now or datetime.now(UTC),
        )
