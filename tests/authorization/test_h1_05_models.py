"""Unit-level fixed-role authorization contracts for H1-05."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint

import app.models  # noqa: F401
from app.authorization.contracts import (
    AUTHORIZATION_POLICY_VERSION,
    AuthorizationDecision,
    AuthorizationRequest,
    DecisionEffect,
    ReasonCode,
)
from app.authorization.models import Permission, RolePermission
from app.memberships.models import FixedMembershipRole, Role, WorkspaceMembership


def test_existing_fixed_role_is_the_canonical_role_model() -> None:
    assert Role is FixedMembershipRole
    assert Role.__tablename__ == "fixed_membership_roles"
    assert "workspace_memberships" == WorkspaceMembership.__tablename__


def test_permission_definitions_are_versioned_and_active() -> None:
    assert set(Permission.__table__.columns.keys()) == {
        "active",
        "created_at",
        "description",
        "permission_key",
        "version",
    }
    assert tuple(Permission.__table__.primary_key.columns.keys()) == (
        "permission_key",
        "version",
    )
    checks = {
        constraint.name
        for constraint in Permission.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_permissions_version" in checks


def test_role_permission_has_explicit_effect_and_no_inheritance() -> None:
    assert set(RolePermission.__table__.columns.keys()) == {
        "created_at",
        "effect",
        "permission_key",
        "permission_version",
        "role_key",
        "role_version",
    }
    foreign_keys = {
        tuple(constraint.column_keys)
        for constraint in RolePermission.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert ("role_key", "role_version") in foreign_keys
    assert ("permission_key", "permission_version") in foreign_keys
    assert "parent_role_id" not in RolePermission.__table__.columns
    assert "inherits_from" not in RolePermission.__table__.columns


def test_authorization_request_rejects_missing_or_unversioned_permission() -> None:
    values = {
        "actor_id": uuid4(),
        "session_id": uuid4(),
        "organization_id": uuid4(),
        "requested_workspace_id": uuid4(),
        "membership_workspace_id": uuid4(),
        "membership_id": uuid4(),
        "permission_key": "read_content",
    }
    with pytest.raises(ValueError, match="permission key"):
        AuthorizationRequest(**{**values, "permission_key": " "})
    with pytest.raises(ValueError, match="positive"):
        AuthorizationRequest(**values, permission_version=0)


def test_decision_contract_is_versioned_and_deterministic() -> None:
    now = datetime.now(UTC)
    allowed = AuthorizationDecision.allow(1, now=now)
    denied = AuthorizationDecision.deny(ReasonCode.EXPLICIT_DENY, 1, now=now)

    assert allowed.effect is DecisionEffect.ALLOW
    assert allowed.policy_version == AUTHORIZATION_POLICY_VERSION
    assert denied.effect is DecisionEffect.DENY
    assert denied.reason is ReasonCode.EXPLICIT_DENY
    assert denied.decided_at == allowed.decided_at
