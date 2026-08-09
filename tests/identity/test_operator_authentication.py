"""Provider-neutral ADR-035 operator identity-to-session contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.identity.operator_auth import (
    OperatorAuthenticationError,
    OperatorAuthenticationService,
    OperatorSessionGrant,
    VerifiedExternalIdentity,
)


class FakeRepository:
    def __init__(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4(), status="active")
        self.link = SimpleNamespace(user_id=self.user.id, status="active")
        self.workspace = SimpleNamespace(
            id=uuid.uuid4(), organization_id=uuid.uuid4(), cell_id="primary", status="active"
        )
        self.membership = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=self.user.id,
            organization_id=self.workspace.organization_id,
            workspace_id=self.workspace.id,
            role_key="workspace_admin",
            role_version=1,
            status="active",
        )
        self.effects = frozenset({"allow"})

    async def resolve_identity(self, *, issuer: str, subject: str):
        assert issuer == "https://accounts.google.com"
        assert subject == "google-subject"
        return self.link, self.user

    async def workspace_for_login(self, workspace_id: uuid.UUID):
        return self.workspace if workspace_id == self.workspace.id else None

    async def membership_for_login(self, *, workspace_id: uuid.UUID, user_id: uuid.UUID):
        if workspace_id == self.workspace.id and user_id == self.user.id:
            return self.membership
        return None

    async def role_permission_effects(self, *, role_key: str, role_version: int):
        assert role_key == self.membership.role_key
        assert role_version == self.membership.role_version
        return self.effects


class FakeIssuer:
    def __init__(self) -> None:
        self.calls = 0

    async def issue(self, **values: object) -> OperatorSessionGrant:
        self.calls += 1
        return OperatorSessionGrant(
            workspace_id=values["workspace_id"],
            user_id=values["user_id"],
            membership_id=values["membership_id"],
            session_id=uuid.uuid4(),
            raw_session="session-secret-not-in-response",
            csrf_token="csrf-secret-not-in-response",
            expires_at=values["expires_at"],
        )


def _claims(now: datetime) -> VerifiedExternalIdentity:
    return VerifiedExternalIdentity(
        issuer="https://accounts.google.com",
        subject="google-subject",
        email="operator@example.com",
        email_verified=True,
    )


@pytest.mark.asyncio
async def test_existing_identity_membership_and_allow_precede_session_issuance() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    repository = FakeRepository()
    issuer = FakeIssuer()
    service = OperatorAuthenticationService(repository, issuer)

    grant = await service.authenticate(
        claims=_claims(now),
        workspace_id=repository.workspace.id,
        device_id="browser-device",
        now=now,
    )

    assert grant.user_id == repository.user.id
    assert grant.membership_id == repository.membership.id
    assert issuer.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda repo: setattr(repo.link, "status", "revoked"), "identity"),
        (lambda repo: setattr(repo.user, "status", "disabled"), "identity"),
        (lambda repo: setattr(repo.membership, "status", "suspended"), "membership"),
        (lambda repo: setattr(repo, "effects", frozenset()), "authorization"),
        (lambda repo: setattr(repo, "effects", frozenset({"allow", "deny"})), "authorization"),
    ],
)
async def test_identity_membership_and_deny_first_fail_before_session(
    mutation, message: str
) -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    repository = FakeRepository()
    issuer = FakeIssuer()
    mutation(repository)

    with pytest.raises(OperatorAuthenticationError, match=message):
        await OperatorAuthenticationService(repository, issuer).authenticate(
            claims=_claims(now),
            workspace_id=repository.workspace.id,
            device_id="browser-device",
            now=now,
        )

    assert issuer.calls == 0


@pytest.mark.asyncio
async def test_verified_email_is_never_used_as_an_identity_fallback() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    repository = FakeRepository()
    issuer = FakeIssuer()
    repository.link = None
    repository.user = None

    with pytest.raises(OperatorAuthenticationError, match="identity"):
        await OperatorAuthenticationService(repository, issuer).authenticate(
            claims=_claims(now),
            workspace_id=repository.workspace.id,
            device_id="browser-device",
            now=now,
        )

    assert issuer.calls == 0
