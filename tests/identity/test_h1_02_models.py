"""Unit-level canonical identity schema tests for H1-02."""

from sqlalchemy import CheckConstraint, UniqueConstraint

import app.models  # noqa: F401
from app.database.base import Base
from app.identity.models import ExternalIdentityLink, User
from app.models.memory import User as CompatibilityUser


def test_canonical_user_has_lifecycle_verification_and_version_state() -> None:
    expected_columns = {
        "created_at",
        "display_name",
        "email",
        "email_verification_source",
        "email_verified",
        "email_verified_at",
        "id",
        "status",
        "updated_at",
        "version",
    }

    assert expected_columns <= set(User.__table__.columns.keys())
    assert CompatibilityUser is User


def test_user_email_index_is_non_unique_and_email_is_not_identity() -> None:
    email_index = next(
        index for index in User.__table__.indexes if index.name == "ix_users_email"
    )

    assert email_index.unique is not True
    assert not any(
        isinstance(constraint, UniqueConstraint)
        and set(constraint.columns.keys()) == {"email"}
        for constraint in User.__table__.constraints
    )


def test_external_identity_is_unique_only_by_issuer_and_subject() -> None:
    unique_pairs = {
        tuple(constraint.columns.keys())
        for constraint in ExternalIdentityLink.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("issuer", "subject") in unique_pairs
    assert ("email",) not in unique_pairs


def test_identity_models_include_required_integrity_constraints() -> None:
    user_checks = {
        constraint.name
        for constraint in User.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    external_checks = {
        constraint.name
        for constraint in ExternalIdentityLink.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert {
        "ck_users_email_verification_provenance",
        "ck_users_positive_version",
        "ck_users_status",
    } <= user_checks
    assert {
        "ck_external_identity_links_email_verification_provenance",
        "ck_external_identity_links_issuer_subject_present",
        "ck_external_identity_links_positive_version",
        "ck_external_identity_links_status",
    } <= external_checks


def test_h1_02_does_not_add_session_membership_or_permission_tables() -> None:
    prohibited_tables = {
        "invitations",
        "permissions",
        "recovery_tokens",
        "role_assignments",
        "sessions",
        "workspace_memberships",
    }

    assert prohibited_tables.isdisjoint(Base.metadata.tables)
