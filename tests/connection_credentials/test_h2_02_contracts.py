"""Unit acceptance tests for H2-02 credential custody contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.connection_credentials import (
    CredentialMigrationError,
    PhaseOneCredentialSnapshot,
    ShadowMigrationCommand,
)
from app.connection_credentials.contracts import (
    canonical_credential_payload,
    credential_record_type,
    normalize_scopes,
)


def test_encryption_context_binds_provider_kind_and_generation() -> None:
    assert (
        credential_record_type(
            provider_key="google_workspace",
            credential_kind="oauth_grant",
            generation=3,
        )
        == "connection_credential:google_workspace:oauth_grant:g3"
    )


def test_semantically_equivalent_json_has_identical_canonical_payload() -> None:
    assert canonical_credential_payload(b'{"scope":["b","a"],"token":"redacted"}') == (
        canonical_credential_payload(
            b'{ "token": "redacted", "scope": [ "b", "a" ] }'
        )
    )


def test_non_object_or_invalid_legacy_payload_fails_closed() -> None:
    for payload in (b"not-json", b'["not","a","credential"]'):
        with pytest.raises(CredentialMigrationError, match="invalid"):
            canonical_credential_payload(payload)


def test_snapshot_repr_redacts_plaintext_and_ciphertext() -> None:
    snapshot = PhaseOneCredentialSnapshot(
        source_system="gmail_credentials",
        source_record_id=str(uuid4()),
        legacy_ciphertext=b"legacy-sensitive-ciphertext",
        plaintext=b'{"access_token":"sensitive-value"}',
        scopes=("scope.b", "scope.a"),
        updated_at=datetime(2026, 7, 31, tzinfo=UTC),
    )

    rendered = repr(snapshot)
    assert "sensitive" not in rendered
    assert "<redacted>" in rendered
    assert len(snapshot.source_checksum) == 64


def test_shadow_command_and_scopes_are_provider_neutral_and_deterministic() -> None:
    snapshot = PhaseOneCredentialSnapshot(
        source_system="drive_credentials",
        source_record_id=str(uuid4()),
        legacy_ciphertext=b"ciphertext",
        plaintext=b'{"refresh_token":"redacted"}',
        scopes=("scope.b", "scope.a", "scope.a"),
    )
    command = ShadowMigrationCommand(
        connection_id=uuid4(),
        provider_key="google_workspace",
        credential_kind="oauth_grant",
        snapshot=snapshot,
        required_scopes=("scope.a",),
    )

    assert normalize_scopes(list(snapshot.scopes)) == ("scope.a", "scope.b")
    assert command.credential_kind == "oauth_grant"


@pytest.mark.parametrize(
    ("provider", "kind", "generation"),
    [
        ("Google Workspace", "oauth_grant", 1),
        ("google_workspace", "OAuth Grant", 1),
        ("google_workspace", "oauth_grant", 0),
    ],
)
def test_invalid_authenticated_context_fails_before_encryption(
    provider: str,
    kind: str,
    generation: int,
) -> None:
    with pytest.raises(ValueError):
        credential_record_type(
            provider_key=provider,
            credential_kind=kind,
            generation=generation,
        )
