"""Unit contracts for the one-time ADR-036 identity bootstrap."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest

from app.identity.bootstrap import (
    FIXED_BOOTSTRAP_USER_ID,
    FIXED_BOOTSTRAP_WORKSPACE_ID,
    BootstrapApproval,
    BootstrapIdentity,
    BootstrapIdentityError,
)


def test_verified_identity_uses_only_normalized_issuer_and_subject() -> None:
    identity = BootstrapIdentity(
        issuer="https://accounts.google.com",
        subject="123456789012345678901",
        audience="client.apps.googleusercontent.com",
        verified_at=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert identity.subject_fingerprint == hashlib.sha256(
        identity.subject.encode()
    ).hexdigest()
    assert "email" not in identity.__dataclass_fields__
    assert "token" not in identity.__dataclass_fields__
    assert "123456789012345678901" not in repr(identity)


@pytest.mark.parametrize(
    ("issuer", "subject"),
    [
        ("accounts.google.com", "123"),
        ("https://issuer.example", "123"),
        ("https://accounts.google.com", ""),
    ],
)
def test_bootstrap_identity_rejects_unverified_shape(issuer: str, subject: str) -> None:
    with pytest.raises(BootstrapIdentityError):
        BootstrapIdentity(
            issuer=issuer,
            subject=subject,
            audience="client.apps.googleusercontent.com",
            verified_at=datetime(2026, 8, 9, tzinfo=UTC),
        )


def test_approval_must_bind_exact_identity_and_fixed_target() -> None:
    identity = BootstrapIdentity(
        issuer="https://accounts.google.com",
        subject="123456789012345678901",
        audience="client.apps.googleusercontent.com",
        verified_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    approval = BootstrapApproval(
        reference="ADR-036-BOOTSTRAP-2026-08-09-01",
        user_id=FIXED_BOOTSTRAP_USER_ID,
        workspace_id=FIXED_BOOTSTRAP_WORKSPACE_ID,
        issuer=identity.issuer,
        subject=identity.subject,
    )

    assert approval.authorizes(identity)
    assert not BootstrapApproval(
        reference=approval.reference,
        user_id=uuid.uuid4(),
        workspace_id=approval.workspace_id,
        issuer=approval.issuer,
        subject=approval.subject,
    ).authorizes(identity)
    assert not BootstrapApproval(
        reference=approval.reference,
        user_id=approval.user_id,
        workspace_id=approval.workspace_id,
        issuer=approval.issuer,
        subject="different-subject",
    ).authorizes(identity)
