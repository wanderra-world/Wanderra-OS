"""Disposable H0 prototype for the Atlas authorization contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID


class Role(StrEnum):
    ORGANIZATION_OWNER = "organization_owner"
    ORGANIZATION_ADMIN = "organization_admin"
    WORKSPACE_OWNER = "workspace_owner"
    WORKSPACE_ADMIN = "workspace_admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Capability(StrEnum):
    READ_CONTENT = "read_content"
    UPDATE_CONTENT = "update_content"
    DELETE_CONTENT = "delete_content"
    MANAGE_WORKSPACE = "manage_workspace"
    MANAGE_ORGANIZATION = "manage_organization"


class AuthenticationStrength(StrEnum):
    SINGLE_FACTOR = "single_factor"
    MFA = "mfa"


class Risk(StrEnum):
    ORDINARY = "ordinary"
    HIGH = "high"


class DecisionEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class ReasonCode(StrEnum):
    ALLOWED = "allowed"
    INVALID_ACTOR = "invalid_actor"
    INVALID_SESSION = "invalid_session"
    INVALID_MEMBERSHIP = "invalid_membership"
    INVALID_DELEGATION = "invalid_delegation"
    WORKSPACE_MISMATCH = "workspace_mismatch"
    LEGAL_RESTRICTION = "legal_restriction"
    CLASSIFICATION_RESTRICTION = "classification_restriction"
    SECURITY_RESTRICTION = "security_restriction"
    ROLE_PERMISSION_MISSING = "role_permission_missing"
    CONTEXT_RESTRICTION = "context_restriction"
    RESOURCE_RESTRICTION = "resource_restriction"
    STEP_UP_REQUIRED = "step_up_required"
    APPROVAL_REQUIRED = "approval_required"


class Obligation(StrEnum):
    REQUIRE_MFA = "require_mfa"
    REQUIRE_APPROVAL = "require_approval"


ROLE_PERMISSIONS: Final = MappingProxyType(
    {
        Role.ORGANIZATION_OWNER: frozenset(
            {
                Capability.READ_CONTENT,
                Capability.UPDATE_CONTENT,
                Capability.DELETE_CONTENT,
                Capability.MANAGE_WORKSPACE,
                Capability.MANAGE_ORGANIZATION,
            }
        ),
        Role.ORGANIZATION_ADMIN: frozenset({Capability.MANAGE_ORGANIZATION}),
        Role.WORKSPACE_OWNER: frozenset(
            {
                Capability.READ_CONTENT,
                Capability.UPDATE_CONTENT,
                Capability.DELETE_CONTENT,
                Capability.MANAGE_WORKSPACE,
            }
        ),
        Role.WORKSPACE_ADMIN: frozenset(
            {
                Capability.READ_CONTENT,
                Capability.UPDATE_CONTENT,
                Capability.DELETE_CONTENT,
                Capability.MANAGE_WORKSPACE,
            }
        ),
        Role.MEMBER: frozenset(
            {Capability.READ_CONTENT, Capability.UPDATE_CONTENT}
        ),
        Role.VIEWER: frozenset({Capability.READ_CONTENT}),
    }
)


@dataclass(frozen=True, slots=True)
class AuthorizationInput:
    """Complete authorization context for one command or query boundary."""

    actor_id: UUID
    session_id: UUID
    organization_id: UUID
    requested_workspace_id: UUID
    membership_workspace_id: UUID
    role: Role
    capability: Capability
    authentication_strength: AuthenticationStrength
    risk: Risk = Risk.ORDINARY
    actor_valid: bool = True
    session_valid: bool = True
    membership_valid: bool = True
    delegation_present: bool = False
    delegation_valid: bool = True
    legal_allows: bool = True
    classification_allows: bool = True
    security_allows: bool = True
    context_allows: bool = True
    resource_allows: bool = True
    approval_required: bool = False
    approval_valid: bool = False
    connection_id: UUID | None = None
    request_reference: str = "request"

    def __post_init__(self) -> None:
        if not self.request_reference.strip():
            raise ValueError("request reference is required")


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    effect: DecisionEffect
    reason: ReasonCode
    policy_version: str
    obligations: tuple[Obligation, ...] = ()


class AuthorizationPolicy:
    """Deny-by-default evaluator implementing the normative precedence order."""

    VERSION = "h0-p0.4-v1"

    def decide(self, request: AuthorizationInput) -> AuthorizationDecision:
        if not request.actor_valid:
            return self._deny(ReasonCode.INVALID_ACTOR)
        if not request.session_valid:
            return self._deny(ReasonCode.INVALID_SESSION)
        if not request.membership_valid:
            return self._deny(ReasonCode.INVALID_MEMBERSHIP)
        if request.delegation_present and not request.delegation_valid:
            return self._deny(ReasonCode.INVALID_DELEGATION)
        if request.requested_workspace_id != request.membership_workspace_id:
            return self._deny(ReasonCode.WORKSPACE_MISMATCH)
        if not request.legal_allows:
            return self._deny(ReasonCode.LEGAL_RESTRICTION)
        if not request.classification_allows:
            return self._deny(ReasonCode.CLASSIFICATION_RESTRICTION)
        if not request.security_allows:
            return self._deny(ReasonCode.SECURITY_RESTRICTION)
        if request.capability not in ROLE_PERMISSIONS[request.role]:
            return self._deny(ReasonCode.ROLE_PERMISSION_MISSING)
        if not request.context_allows:
            return self._deny(ReasonCode.CONTEXT_RESTRICTION)
        if not request.resource_allows:
            return self._deny(ReasonCode.RESOURCE_RESTRICTION)
        if (
            request.risk is Risk.HIGH
            and request.authentication_strength is not AuthenticationStrength.MFA
        ):
            return self._deny(
                ReasonCode.STEP_UP_REQUIRED,
                obligations=(Obligation.REQUIRE_MFA,),
            )
        if request.approval_required and not request.approval_valid:
            return self._deny(
                ReasonCode.APPROVAL_REQUIRED,
                obligations=(Obligation.REQUIRE_APPROVAL,),
            )
        return AuthorizationDecision(
            effect=DecisionEffect.ALLOW,
            reason=ReasonCode.ALLOWED,
            policy_version=self.VERSION,
        )

    def _deny(
        self,
        reason: ReasonCode,
        *,
        obligations: tuple[Obligation, ...] = (),
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            effect=DecisionEffect.DENY,
            reason=reason,
            policy_version=self.VERSION,
            obligations=obligations,
        )
