"""Unit-level security and schema contracts for H1-03."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import CheckConstraint

import app.models  # noqa: F401
from app.identity.lifecycle import (
    IdentityLifecycleError,
    InvalidSessionError,
    SessionCookiePolicy,
    hash_secret,
    validate_csrf,
)
from app.identity.lifecycle_models import (
    IdentityLifecycleToken,
    IdentitySession,
    SecurityNotification,
)
from app.identity.models import ExternalIdentityLink, User


def test_raw_identity_secrets_are_never_part_of_the_persistence_schema() -> None:
    for model in (IdentitySession, IdentityLifecycleToken):
        columns = set(model.__table__.columns.keys())
        assert "token_hash" in columns
        assert {"token", "raw_secret", "secret"}.isdisjoint(columns)

    raw_secret = "a-secure-random-value-that-is-long-enough"
    assert hash_secret(raw_secret) == hashlib.sha256(raw_secret.encode()).hexdigest()
    assert raw_secret not in hash_secret(raw_secret)
    with pytest.raises(IdentityLifecycleError):
        hash_secret("too-short")


def test_browser_session_cookie_and_csrf_contract_is_secure() -> None:
    policy = SessionCookiePolicy()
    assert policy.name.startswith("__Host-")
    assert policy.secure is True
    assert policy.http_only is True
    assert policy.same_site == "lax"
    assert policy.path == "/"

    validate_csrf("same-secret", "same-secret")
    for cookie, header in ((None, "x"), ("x", None), ("x", "y")):
        with pytest.raises(InvalidSessionError):
            validate_csrf(cookie, header)


def test_lifecycle_models_expose_only_the_approved_h1_03_state() -> None:
    assert {
        "authentication_strength",
        "device_id",
        "expires_at",
        "last_seen_at",
        "mfa_authenticated_at",
        "revoked_at",
    } <= set(IdentitySession.__table__.columns.keys())
    assert {"purpose", "scope", "consumed_at", "revoked_at"} <= set(
        IdentityLifecycleToken.__table__.columns.keys()
    )
    assert {"event_type", "payload", "status"} <= set(
        SecurityNotification.__table__.columns.keys()
    )
    assert "mfa_required" in User.__table__.columns
    assert {"proofed_at", "proof_reference", "review_expires_at"} <= set(
        ExternalIdentityLink.__table__.columns.keys()
    )


def test_identity_link_review_evidence_is_database_enforced() -> None:
    checks = {
        constraint.name
        for constraint in ExternalIdentityLink.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_external_identity_links_review_evidence" in checks


def test_h1_03_does_not_introduce_h1_04_authorization_tables() -> None:
    prohibited = {
        "capabilities",
        "role_assignments",
        "roles",
        "workspace_memberships",
    }
    h1_03_tables = {
        IdentityLifecycleToken.__tablename__,
        IdentitySession.__tablename__,
        SecurityNotification.__tablename__,
    }
    assert prohibited.isdisjoint(h1_03_tables)
