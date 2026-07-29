"""Authorization decision matrix for the disposable H0-04 prototype."""

from dataclasses import replace
from uuid import uuid4

import pytest

from tests.architecture.authorization_prototype import (
    AuthenticationStrength,
    AuthorizationInput,
    AuthorizationPolicy,
    Capability,
    DecisionEffect,
    Obligation,
    ReasonCode,
    Risk,
    Role,
)

WORKSPACE_ID = uuid4()


def request(**changes: object) -> AuthorizationInput:
    baseline = AuthorizationInput(
        actor_id=uuid4(),
        session_id=uuid4(),
        organization_id=uuid4(),
        requested_workspace_id=WORKSPACE_ID,
        membership_workspace_id=WORKSPACE_ID,
        role=Role.MEMBER,
        capability=Capability.UPDATE_CONTENT,
        authentication_strength=AuthenticationStrength.MFA,
        connection_id=uuid4(),
        request_reference="request-001",
    )
    return replace(baseline, **changes)


def assert_denied(
    authorization_input: AuthorizationInput,
    reason: ReasonCode,
) -> None:
    decision = AuthorizationPolicy().decide(authorization_input)
    assert decision.effect is DecisionEffect.DENY
    assert decision.reason is reason
    assert decision.policy_version == AuthorizationPolicy.VERSION


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"actor_valid": False}, ReasonCode.INVALID_ACTOR),
        ({"session_valid": False}, ReasonCode.INVALID_SESSION),
        ({"membership_valid": False}, ReasonCode.INVALID_MEMBERSHIP),
        (
            {"delegation_present": True, "delegation_valid": False},
            ReasonCode.INVALID_DELEGATION,
        ),
    ],
)
def test_fit_authz_001_invalid_security_principal_denies(
    change: dict[str, object],
    reason: ReasonCode,
) -> None:
    """FIT-AUTHZ-001 denies invalid identity, session, membership, or delegation."""

    assert_denied(request(**change), reason)


def test_fit_authz_002_workspace_mismatch_denies() -> None:
    """FIT-AUTHZ-002 prevents authorization across workspace boundaries."""

    assert_denied(
        request(membership_workspace_id=uuid4()),
        ReasonCode.WORKSPACE_MISMATCH,
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"legal_allows": False}, ReasonCode.LEGAL_RESTRICTION),
        (
            {"classification_allows": False},
            ReasonCode.CLASSIFICATION_RESTRICTION,
        ),
        ({"security_allows": False}, ReasonCode.SECURITY_RESTRICTION),
    ],
)
def test_fit_authz_003_governance_denies_take_precedence(
    change: dict[str, object],
    reason: ReasonCode,
) -> None:
    """FIT-AUTHZ-003 applies legal, classification, and security denies."""

    assert_denied(request(**change), reason)


@pytest.mark.parametrize(
    ("role", "capability", "allowed"),
    [
        (Role.ORGANIZATION_OWNER, Capability.MANAGE_ORGANIZATION, True),
        (Role.ORGANIZATION_ADMIN, Capability.MANAGE_ORGANIZATION, True),
        (Role.ORGANIZATION_ADMIN, Capability.READ_CONTENT, False),
        (Role.WORKSPACE_OWNER, Capability.MANAGE_WORKSPACE, True),
        (Role.WORKSPACE_ADMIN, Capability.MANAGE_WORKSPACE, True),
        (Role.MEMBER, Capability.UPDATE_CONTENT, True),
        (Role.MEMBER, Capability.DELETE_CONTENT, False),
        (Role.VIEWER, Capability.READ_CONTENT, True),
        (Role.VIEWER, Capability.UPDATE_CONTENT, False),
    ],
)
def test_fit_authz_004_fixed_role_permission_matrix(
    role: Role,
    capability: Capability,
    allowed: bool,
) -> None:
    """FIT-AUTHZ-004 validates fixed, explicit role templates."""

    decision = AuthorizationPolicy().decide(
        request(role=role, capability=capability)
    )

    assert (decision.effect is DecisionEffect.ALLOW) is allowed
    if not allowed:
        assert decision.reason is ReasonCode.ROLE_PERMISSION_MISSING


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"context_allows": False}, ReasonCode.CONTEXT_RESTRICTION),
        ({"resource_allows": False}, ReasonCode.RESOURCE_RESTRICTION),
    ],
)
def test_fit_authz_005_context_and_resource_grants_only_narrow(
    change: dict[str, object],
    reason: ReasonCode,
) -> None:
    """FIT-AUTHZ-005 proves narrower grants can deny an otherwise valid role."""

    assert_denied(request(**change), reason)

    assert_denied(
        request(
            role=Role.VIEWER,
            capability=Capability.DELETE_CONTENT,
            **change,
        ),
        ReasonCode.ROLE_PERMISSION_MISSING,
    )


def test_fit_authz_006_approval_never_grants_permission() -> None:
    """FIT-AUTHZ-006 prevents approval from overriding missing permission."""

    assert_denied(
        request(
            role=Role.VIEWER,
            capability=Capability.DELETE_CONTENT,
            approval_required=True,
            approval_valid=True,
        ),
        ReasonCode.ROLE_PERMISSION_MISSING,
    )


def test_fit_authz_007_high_risk_operation_requires_step_up() -> None:
    """FIT-AUTHZ-007 returns an MFA obligation for insufficient authentication."""

    decision = AuthorizationPolicy().decide(
        request(
            risk=Risk.HIGH,
            authentication_strength=AuthenticationStrength.SINGLE_FACTOR,
        )
    )

    assert decision.effect is DecisionEffect.DENY
    assert decision.reason is ReasonCode.STEP_UP_REQUIRED
    assert decision.obligations == (Obligation.REQUIRE_MFA,)


def test_fit_authz_008_required_approval_must_be_satisfied() -> None:
    """FIT-AUTHZ-008 emits an approval obligation and allows it when valid."""

    missing = AuthorizationPolicy().decide(
        request(approval_required=True, approval_valid=False)
    )
    satisfied = AuthorizationPolicy().decide(
        request(approval_required=True, approval_valid=True)
    )

    assert missing.effect is DecisionEffect.DENY
    assert missing.reason is ReasonCode.APPROVAL_REQUIRED
    assert missing.obligations == (Obligation.REQUIRE_APPROVAL,)
    assert satisfied.effect is DecisionEffect.ALLOW


def test_fit_authz_009_deny_precedence_is_stable() -> None:
    """FIT-AUTHZ-009 applies the documented precedence when failures overlap."""

    decision = AuthorizationPolicy().decide(
        request(
            session_valid=False,
            membership_workspace_id=uuid4(),
            legal_allows=False,
            role=Role.VIEWER,
            capability=Capability.DELETE_CONTENT,
            approval_required=True,
        )
    )

    assert decision.reason is ReasonCode.INVALID_SESSION


def test_fit_authz_010_valid_complete_input_allows() -> None:
    """FIT-AUTHZ-010 allows only a fully authorized command or query."""

    decision = AuthorizationPolicy().decide(request())

    assert decision.effect is DecisionEffect.ALLOW
    assert decision.reason is ReasonCode.ALLOWED
    assert decision.obligations == ()
