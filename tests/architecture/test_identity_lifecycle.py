"""Lifecycle and negative-path matrix for the H0-03 identity prototype."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.architecture.identity_prototype import (
    AuthenticationError,
    AuthenticationStrength,
    ExternalIdentityRegistry,
    IdentityLifecycleError,
    IdentityLinkEvidence,
    InvitationError,
    InvitationStore,
    RecoveryError,
    RecoveryService,
    ServicePrincipal,
    SessionStore,
    User,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def strong_link_evidence() -> IdentityLinkEvidence:
    return IdentityLinkEvidence(
        recent_strong_authentication=True,
        external_identity_proven=True,
        audit_reference="audit-link-001",
    )


def test_fit_identity_001_external_identity_is_unique_by_issuer_and_subject() -> None:
    """FIT-IDENTITY-001 prevents one login identity from linking twice."""

    registry = ExternalIdentityRegistry()
    registry.link(
        user=User(id=uuid4()),
        issuer="https://identity.example",
        subject="subject-1",
        verified_email="person@example.com",
        evidence=strong_link_evidence(),
        now=NOW,
    )

    with pytest.raises(IdentityLifecycleError, match="already linked"):
        registry.link(
            user=User(id=uuid4()),
            issuer="https://identity.example",
            subject="subject-1",
            verified_email="other@example.com",
            evidence=strong_link_evidence(),
            now=NOW,
        )


def test_fit_identity_002_verified_email_never_merges_users() -> None:
    """FIT-IDENTITY-002 treats verified email as an attribute, not an identity key."""

    registry = ExternalIdentityRegistry()
    first_user = User(id=uuid4(), verified_email="shared@example.com")
    second_user = User(id=uuid4(), verified_email="shared@example.com")

    first_link = registry.link(
        user=first_user,
        issuer="https://identity-a.example",
        subject="subject-a",
        verified_email="shared@example.com",
        evidence=strong_link_evidence(),
        now=NOW,
    )
    second_link = registry.link(
        user=second_user,
        issuer="https://identity-b.example",
        subject="subject-b",
        verified_email="shared@example.com",
        evidence=strong_link_evidence(),
        now=NOW,
    )

    assert first_link.user_id != second_link.user_id
    with pytest.raises(IdentityLifecycleError, match="merging by email is prohibited"):
        registry.merge_users_by_email("shared@example.com")


@pytest.mark.parametrize(
    ("recent_authentication", "external_proof", "message"),
    [
        (False, True, "strong authentication"),
        (True, False, "identity proof"),
    ],
)
def test_fit_identity_003_linking_requires_both_proofs(
    recent_authentication: bool,
    external_proof: bool,
    message: str,
) -> None:
    """FIT-IDENTITY-003 rejects incompletely proven identity links."""

    evidence = IdentityLinkEvidence(
        recent_strong_authentication=recent_authentication,
        external_identity_proven=external_proof,
        audit_reference="audit-link-002",
    )

    with pytest.raises(IdentityLifecycleError, match=message):
        ExternalIdentityRegistry().link(
            user=User(id=uuid4()),
            issuer="https://identity.example",
            subject="subject-2",
            verified_email=None,
            evidence=evidence,
            now=NOW,
        )


def test_fit_session_001_only_a_digest_is_stored() -> None:
    """FIT-SESSION-001 never persists the opaque raw session token."""

    store = SessionStore()
    session, raw_token = store.issue(
        user_id=uuid4(),
        device_reference="device-1",
        authentication_strength=AuthenticationStrength.MFA,
        now=NOW,
        idle_ttl=timedelta(hours=1),
        absolute_ttl=timedelta(days=1),
    )

    assert raw_token not in repr(session)
    assert session.token_digest != raw_token
    assert len(session.token_digest) == 64
    assert store.authenticate(raw_token, now=NOW) == session


def test_fit_session_002_revocation_applies_on_the_next_transaction() -> None:
    """FIT-SESSION-002 proves authorization reads current revocation state."""

    store = SessionStore()
    session, raw_token = store.issue(
        user_id=uuid4(),
        device_reference="device-2",
        authentication_strength=AuthenticationStrength.MFA,
        now=NOW,
        idle_ttl=timedelta(hours=1),
        absolute_ttl=timedelta(days=1),
    )
    assert store.authenticate(raw_token, now=NOW) == session

    store.revoke_session(session.id, now=NOW + timedelta(seconds=1))

    with pytest.raises(AuthenticationError, match="revoked"):
        store.authenticate(raw_token, now=NOW + timedelta(seconds=2))


@pytest.mark.parametrize(
    ("strength", "elapsed", "message"),
    [
        (AuthenticationStrength.SINGLE_FACTOR, timedelta(minutes=1), "requires MFA"),
        (AuthenticationStrength.MFA, timedelta(minutes=16), "recent authentication"),
    ],
)
def test_fit_session_003_privileged_access_requires_recent_mfa(
    strength: AuthenticationStrength,
    elapsed: timedelta,
    message: str,
) -> None:
    """FIT-SESSION-003 enforces authentication strength and freshness."""

    store = SessionStore()
    _, raw_token = store.issue(
        user_id=uuid4(),
        device_reference="device-3",
        authentication_strength=strength,
        now=NOW,
        idle_ttl=timedelta(hours=1),
        absolute_ttl=timedelta(days=1),
    )

    with pytest.raises(AuthenticationError, match=message):
        store.authenticate(raw_token, now=NOW + elapsed, privileged=True)


def test_fit_session_004_idle_and_absolute_expiry_are_enforced() -> None:
    """FIT-SESSION-004 rejects both session expiry modes."""

    idle_store = SessionStore()
    _, idle_token = idle_store.issue(
        user_id=uuid4(),
        device_reference="idle-device",
        authentication_strength=AuthenticationStrength.MFA,
        now=NOW,
        idle_ttl=timedelta(minutes=10),
        absolute_ttl=timedelta(hours=1),
    )
    with pytest.raises(AuthenticationError, match="idle expiry"):
        idle_store.authenticate(idle_token, now=NOW + timedelta(minutes=10))

    absolute_store = SessionStore()
    _, absolute_token = absolute_store.issue(
        user_id=uuid4(),
        device_reference="absolute-device",
        authentication_strength=AuthenticationStrength.MFA,
        now=NOW,
        idle_ttl=timedelta(hours=1),
        absolute_ttl=timedelta(hours=1),
    )
    with pytest.raises(AuthenticationError, match="idle expiry|absolute expiry"):
        absolute_store.authenticate(absolute_token, now=NOW + timedelta(hours=1))


def test_fit_invitation_001_is_hashed_scoped_single_use_and_short_lived() -> None:
    """FIT-INVITE-001 proves the secure invitation lifecycle."""

    store = InvitationStore()
    invitation, raw_token = store.issue(
        inviter_user_id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        intended_email="Person@Example.com",
        now=NOW,
    )

    assert raw_token not in repr(invitation)
    accepted = store.accept(
        raw_token,
        claimant_email="person@example.com",
        now=NOW + timedelta(hours=1),
        inviter_is_authorized=True,
        target_policy_allows=True,
    )
    assert accepted.accepted_at == NOW + timedelta(hours=1)

    with pytest.raises(InvitationError, match="already used"):
        store.accept(
            raw_token,
            claimant_email="person@example.com",
            now=NOW + timedelta(hours=2),
            inviter_is_authorized=True,
            target_policy_allows=True,
        )

    with pytest.raises(InvitationError, match="within 72 hours"):
        store.issue(
            inviter_user_id=uuid4(),
            organization_id=uuid4(),
            workspace_id=uuid4(),
            intended_email="person@example.com",
            now=NOW,
            ttl=timedelta(hours=73),
        )


@pytest.mark.parametrize(
    ("email", "authorized", "policy_allows", "message"),
    [
        ("wrong@example.com", True, True, "email does not match"),
        ("person@example.com", False, True, "authority"),
        ("person@example.com", True, False, "policy"),
    ],
)
def test_fit_invitation_002_acceptance_rechecks_security_context(
    email: str,
    authorized: bool,
    policy_allows: bool,
    message: str,
) -> None:
    """FIT-INVITE-002 rechecks identity, inviter authority, and policy."""

    store = InvitationStore()
    _, raw_token = store.issue(
        inviter_user_id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        intended_email="person@example.com",
        now=NOW,
    )

    with pytest.raises(InvitationError, match=message):
        store.accept(
            raw_token,
            claimant_email=email,
            now=NOW + timedelta(hours=1),
            inviter_is_authorized=authorized,
            target_policy_allows=policy_allows,
        )


def test_fit_invitation_003_expired_invitation_is_rejected() -> None:
    """FIT-INVITE-003 rejects use at or after the expiry boundary."""

    store = InvitationStore()
    invitation, raw_token = store.issue(
        inviter_user_id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        intended_email="person@example.com",
        now=NOW,
        ttl=timedelta(hours=2),
    )

    with pytest.raises(InvitationError, match="expired"):
        store.accept(
            raw_token,
            claimant_email="person@example.com",
            now=invitation.expires_at,
            inviter_is_authorized=True,
            target_policy_allows=True,
        )


@pytest.mark.parametrize(
    ("channel_verified", "step_up_verified", "message"),
    [
        (False, True, "recovery channel"),
        (True, False, "step-up"),
    ],
)
def test_fit_recovery_001_requires_channel_and_step_up_verification(
    channel_verified: bool,
    step_up_verified: bool,
    message: str,
) -> None:
    """FIT-RECOVERY-001 rejects incomplete account-recovery proof."""

    sessions = SessionStore()
    recovery = RecoveryService(sessions)
    _, raw_token = recovery.issue(
        user_id=uuid4(),
        now=NOW,
        ttl=timedelta(minutes=30),
    )

    with pytest.raises(RecoveryError, match=message):
        recovery.complete(
            raw_token,
            now=NOW + timedelta(minutes=1),
            recovery_channel_verified=channel_verified,
            step_up_verified=step_up_verified,
        )


def test_fit_recovery_002_revokes_sessions_and_all_recovery_tokens() -> None:
    """FIT-RECOVERY-002 invalidates credentials and emits security evidence."""

    user_id = uuid4()
    sessions = SessionStore()
    first_session, first_session_token = sessions.issue(
        user_id=user_id,
        device_reference="device-a",
        authentication_strength=AuthenticationStrength.MFA,
        now=NOW,
        idle_ttl=timedelta(hours=1),
        absolute_ttl=timedelta(days=1),
    )
    second_session, _ = sessions.issue(
        user_id=user_id,
        device_reference="device-b",
        authentication_strength=AuthenticationStrength.MFA,
        now=NOW,
        idle_ttl=timedelta(hours=1),
        absolute_ttl=timedelta(days=1),
    )
    recovery = RecoveryService(sessions)
    first_recovery, first_recovery_token = recovery.issue(
        user_id=user_id,
        now=NOW,
        ttl=timedelta(minutes=30),
    )
    second_recovery, second_recovery_token = recovery.issue(
        user_id=user_id,
        now=NOW,
        ttl=timedelta(minutes=30),
    )

    result = recovery.complete(
        first_recovery_token,
        now=NOW + timedelta(minutes=1),
        recovery_channel_verified=True,
        step_up_verified=True,
    )

    assert set(result.revoked_session_ids) == {first_session.id, second_session.id}
    assert set(result.invalidated_recovery_token_ids) == {
        first_recovery.id,
        second_recovery.id,
    }
    assert result.events == (
        "security.identity_recovery_notification",
        "audit.identity_recovery_completed",
    )
    with pytest.raises(AuthenticationError, match="revoked"):
        sessions.authenticate(first_session_token, now=NOW + timedelta(minutes=2))
    with pytest.raises(RecoveryError, match="invalid"):
        recovery.complete(
            second_recovery_token,
            now=NOW + timedelta(minutes=2),
            recovery_channel_verified=True,
            step_up_verified=True,
        )


def test_fit_identity_004_service_principal_is_scoped_expiring_and_revocable() -> None:
    """FIT-IDENTITY-004 proves explicit non-human identity lifecycle."""

    principal = ServicePrincipal(
        id=uuid4(),
        owner_user_id=uuid4(),
        workspace_id=uuid4(),
        purpose="provider reconciliation",
        expires_at=NOW + timedelta(hours=1),
    )

    assert principal.is_active(now=NOW)
    assert not principal.is_active(now=principal.expires_at)
    assert not principal.revoke(now=NOW).is_active(now=NOW)
