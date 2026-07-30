"""Unit-level workspace membership contracts for H1-04."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import app.models  # noqa: F401
from app.memberships.contracts import (
    FIXED_MEMBERSHIP_ROLES,
    FIXED_ROLE_DEFINITIONS,
    MEMBERSHIP_ROLE_VERSION,
    WORKSPACE_MEMBERSHIP_ROLES,
)
from app.memberships.models import FixedMembershipRole, WorkspaceMembership


def test_fixed_role_definitions_are_complete_deterministic_and_versioned() -> None:
    assert MEMBERSHIP_ROLE_VERSION == 1
    assert FIXED_MEMBERSHIP_ROLES == {
        "organization_owner",
        "organization_admin",
        "workspace_owner",
        "workspace_admin",
        "member",
        "viewer",
    }
    assert tuple(definition.key for definition in FIXED_ROLE_DEFINITIONS) == tuple(
        sorted(FIXED_MEMBERSHIP_ROLES)
    )
    assert all(definition.version == 1 for definition in FIXED_ROLE_DEFINITIONS)
    assert WORKSPACE_MEMBERSHIP_ROLES == {
        "workspace_owner",
        "workspace_admin",
        "member",
        "viewer",
    }


def test_membership_links_user_organization_and_workspace() -> None:
    foreign_keys = {
        tuple(constraint.column_keys)
        for constraint in WorkspaceMembership.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert ("workspace_id", "organization_id") in foreign_keys
    assert ("user_id",) in foreign_keys
    assert ("role_key", "role_version") in foreign_keys


def test_membership_has_lifecycle_revocation_and_invitation_state() -> None:
    assert {
        "accepted_invitation_token_id",
        "activated_at",
        "invitation_token_id",
        "invited_by_user_id",
        "origin",
        "revocation_reason",
        "revoked_at",
        "role_key",
        "role_version",
        "status",
        "suspended_at",
        "version",
    } <= set(WorkspaceMembership.__table__.columns.keys())

    checks = {
        constraint.name
        for constraint in WorkspaceMembership.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_workspace_memberships_lifecycle",
        "ck_workspace_memberships_origin",
        "ck_workspace_memberships_status",
        "ck_workspace_memberships_version",
        "ck_workspace_memberships_workspace_role",
    } <= checks


def test_membership_keys_prevent_duplicate_and_cross_workspace_identity() -> None:
    unique_keys = {
        tuple(constraint.columns.keys())
        for constraint in WorkspaceMembership.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("workspace_id", "user_id") in unique_keys
    assert ("workspace_id", "invitation_token_id") in unique_keys
    assert ("workspace_id", "accepted_invitation_token_id") in unique_keys
    assert tuple(WorkspaceMembership.__table__.primary_key.columns.keys()) == (
        "workspace_id",
        "id",
    )


def test_fixed_roles_define_classification_without_capabilities() -> None:
    assert set(FixedMembershipRole.__table__.columns.keys()) == {
        "active",
        "created_at",
        "role_key",
        "scope",
        "version",
    }
    prohibited_h1_04_tables = {
        "capabilities",
        "permissions",
        "policy_decisions",
        "role_capabilities",
        "role_permissions",
    }
    assert prohibited_h1_04_tables.isdisjoint(
        {
            FixedMembershipRole.__tablename__,
            WorkspaceMembership.__tablename__,
        }
    )
