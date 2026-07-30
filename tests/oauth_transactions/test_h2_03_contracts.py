"""Failing-first contract tests for the H2-03 OAuth transaction boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.oauth_transactions.contracts import (
    OAuthCallback,
    OAuthCredentialGrant,
    OAuthPurpose,
    OAuthScopeError,
    OAuthSecurityPolicy,
    OAuthStatus,
    OAuthTransactionCreate,
    issue_state_token,
    parse_workspace_hint,
    require_transition,
    state_digest,
    validate_returned_scopes,
)


def test_state_is_opaque_hashed_and_workspace_routable() -> None:
    workspace_id = uuid4()

    raw_state = issue_state_token(workspace_id)

    assert parse_workspace_hint(raw_state) == workspace_id
    assert len(state_digest(raw_state)) == 64
    assert raw_state not in repr(state_digest(raw_state))
    assert " " not in raw_state


def test_transaction_create_normalizes_provider_neutral_security_binding() -> None:
    policy = OAuthSecurityPolicy(
        allowed_redirect_uris=frozenset(
            {"https://atlas.example/api/v1/oauth/callback"}
        ),
        allowed_issuers=frozenset({"https://issuer.example"}),
        allowed_scopes=frozenset({"email.read", "calendar.read", "storage.read"}),
        lifetime=timedelta(minutes=10),
    )

    command = OAuthTransactionCreate(
        transaction_id=uuid4(),
        connection_id=uuid4(),
        provider_key=" provider_one ",
        purpose=OAuthPurpose.CONNECT,
        redirect_uri="https://atlas.example/api/v1/oauth/callback",
        issuer="https://issuer.example",
        requested_capabilities=("storage.read", "email.read", "email.read"),
        requested_scopes=("calendar.read", "email.read", "email.read"),
        required_scopes=("email.read",),
        incremental=True,
    ).validated(policy)

    assert command.provider_key == "provider_one"
    assert command.requested_capabilities == ("email.read", "storage.read")
    assert command.requested_scopes == ("calendar.read", "email.read")
    assert command.required_scopes == ("email.read",)


def test_redirect_issuer_and_scope_allowlists_fail_closed() -> None:
    policy = OAuthSecurityPolicy(
        allowed_redirect_uris=frozenset(
            {"https://atlas.example/api/v1/oauth/callback"}
        ),
        allowed_issuers=frozenset({"https://issuer.example"}),
        allowed_scopes=frozenset({"email.read"}),
    )
    base = dict(
        transaction_id=uuid4(),
        connection_id=uuid4(),
        provider_key="provider_one",
        purpose=OAuthPurpose.CONNECT,
        requested_capabilities=("email.read",),
        requested_scopes=("email.read",),
        required_scopes=("email.read",),
    )

    for changed in (
        {"redirect_uri": "https://attacker.example/callback", "issuer": "https://issuer.example"},
        {"redirect_uri": "https://atlas.example/api/v1/oauth/callback", "issuer": "https://other.example"},
        {
            "redirect_uri": "https://atlas.example/api/v1/oauth/callback",
            "issuer": "https://issuer.example",
            "requested_scopes": ("admin.all",),
        },
    ):
        with pytest.raises(ValueError):
            OAuthTransactionCreate(**{**base, **changed}).validated(policy)


def test_incremental_scope_superset_is_accepted_deterministically() -> None:
    returned = validate_returned_scopes(
        returned_scopes=("storage.read", "calendar.read", "email.read"),
        required_scopes=("email.read", "calendar.read"),
        allowed_scopes=("email.read", "calendar.read", "storage.read"),
    )

    assert returned == ("calendar.read", "email.read", "storage.read")


@pytest.mark.parametrize(
    ("returned", "required", "allowed", "message"),
    [
        (
            ("email.read",),
            ("email.read", "calendar.read"),
            ("email.read", "calendar.read"),
            "missing",
        ),
        (("email.read", "admin.all"), ("email.read",), ("email.read",), "unexpected"),
    ],
)
def test_missing_or_unexpected_returned_scope_fails_closed(
    returned: tuple[str, ...],
    required: tuple[str, ...],
    allowed: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(OAuthScopeError, match=message):
        validate_returned_scopes(
            returned_scopes=returned,
            required_scopes=required,
            allowed_scopes=allowed,
        )


def test_callback_repr_redacts_code_and_state() -> None:
    callback = OAuthCallback(
        state="raw-sensitive-state",
        code="raw-sensitive-code",
        returned_scopes=("email.read",),
        issuer="https://issuer.example",
        redirect_uri="https://atlas.example/api/v1/oauth/callback",
        received_at=datetime(2026, 7, 31, tzinfo=UTC),
    )

    rendered = repr(callback)
    assert "raw-sensitive" not in rendered
    assert rendered.count("<redacted>") >= 2


def test_provider_denial_repr_redacts_callback_material() -> None:
    callback = OAuthCallback(
        state="raw-sensitive-state",
        code=None,
        returned_scopes=(),
        issuer="https://issuer.example",
        redirect_uri="https://atlas.example/api/v1/oauth/callback",
        received_at=datetime(2026, 7, 31, tzinfo=UTC),
        error_code="access_denied",
        error_description="user cancelled",
    )

    rendered = repr(callback)
    assert "raw-sensitive" not in rendered
    assert "user cancelled" not in rendered


def test_credential_handoff_repr_redacts_payload() -> None:
    grant = OAuthCredentialGrant(
        payload=b'{"refresh_token":"raw-sensitive-value"}',
        scopes=("email.read",),
        provider_account_id="account-1",
        credential_kind="oauth_grant",
    )

    assert "raw-sensitive" not in repr(grant)
    assert "<redacted>" in repr(grant)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OAuthStatus.PENDING, OAuthStatus.COMPLETED),
        (OAuthStatus.PENDING, OAuthStatus.CANCELLED),
        (OAuthStatus.PENDING, OAuthStatus.FAILED),
        (OAuthStatus.PENDING, OAuthStatus.EXPIRED),
    ],
)
def test_only_terminal_one_time_transitions_are_allowed(
    current: OAuthStatus,
    target: OAuthStatus,
) -> None:
    require_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OAuthStatus.COMPLETED, OAuthStatus.COMPLETED),
        (OAuthStatus.COMPLETED, OAuthStatus.FAILED),
        (OAuthStatus.CANCELLED, OAuthStatus.COMPLETED),
        (OAuthStatus.FAILED, OAuthStatus.PENDING),
        (OAuthStatus.EXPIRED, OAuthStatus.COMPLETED),
    ],
)
def test_replay_or_terminal_state_transition_is_denied(
    current: OAuthStatus,
    target: OAuthStatus,
) -> None:
    with pytest.raises(ValueError, match="transition"):
        require_transition(current, target)
