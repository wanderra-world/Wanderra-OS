"""Disposable H0 prototype for canonical identity and credential lifecycles."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4


class IdentityLifecycleError(ValueError):
    """Base error for rejected identity lifecycle operations."""


class AuthenticationError(IdentityLifecycleError):
    """Raised when a session cannot authorize the current transaction."""


class InvitationError(IdentityLifecycleError):
    """Raised when an invitation is invalid or cannot be accepted."""


class RecoveryError(IdentityLifecycleError):
    """Raised when account recovery requirements are not satisfied."""


class AuthenticationStrength(StrEnum):
    SINGLE_FACTOR = "single_factor"
    MFA = "mfa"


@dataclass(frozen=True, slots=True)
class User:
    """Canonical global human identity."""

    id: UUID
    verified_email: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityLinkEvidence:
    """Evidence required to link an external login identity."""

    recent_strong_authentication: bool
    external_identity_proven: bool
    audit_reference: str

    def __post_init__(self) -> None:
        if not self.audit_reference.strip():
            raise IdentityLifecycleError("identity-link audit reference is required")


@dataclass(frozen=True, slots=True)
class ExternalIdentityLink:
    """Issuer/subject login identity linked to one canonical user."""

    user_id: UUID
    issuer: str
    subject: str
    verified_email: str | None
    linked_at: datetime
    reversible_until: datetime
    audit_reference: str


class ExternalIdentityRegistry:
    """Registry enforcing issuer/subject uniqueness without email-based merging."""

    def __init__(self) -> None:
        self._links: dict[tuple[str, str], ExternalIdentityLink] = {}

    def link(
        self,
        *,
        user: User,
        issuer: str,
        subject: str,
        verified_email: str | None,
        evidence: IdentityLinkEvidence,
        now: datetime,
        review_window: timedelta = timedelta(days=7),
    ) -> ExternalIdentityLink:
        if not evidence.recent_strong_authentication:
            raise IdentityLifecycleError(
                "recent strong authentication is required to link identity"
            )
        if not evidence.external_identity_proven:
            raise IdentityLifecycleError("external identity proof is required")
        key = (issuer, subject)
        if key in self._links:
            raise IdentityLifecycleError("external issuer and subject already linked")

        link = ExternalIdentityLink(
            user_id=user.id,
            issuer=issuer,
            subject=subject,
            verified_email=verified_email,
            linked_at=now,
            reversible_until=now + review_window,
            audit_reference=evidence.audit_reference,
        )
        self._links[key] = link
        return link

    def resolve(self, issuer: str, subject: str) -> ExternalIdentityLink | None:
        return self._links.get((issuer, subject))

    @staticmethod
    def merge_users_by_email(_email: str) -> None:
        raise IdentityLifecycleError("automatic account merging by email is prohibited")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _opaque_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class Session:
    """Server-side session record that never stores the raw bearer token."""

    id: UUID
    user_id: UUID
    token_digest: str
    device_reference: str
    authentication_strength: AuthenticationStrength
    authenticated_at: datetime
    created_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None


class SessionStore:
    """Current-state session store used for every transaction authorization."""

    def __init__(self) -> None:
        self._sessions: dict[UUID, Session] = {}

    def issue(
        self,
        *,
        user_id: UUID,
        device_reference: str,
        authentication_strength: AuthenticationStrength,
        now: datetime,
        idle_ttl: timedelta,
        absolute_ttl: timedelta,
    ) -> tuple[Session, str]:
        if idle_ttl <= timedelta(0) or absolute_ttl <= timedelta(0):
            raise IdentityLifecycleError("session expiry must be in the future")
        if idle_ttl > absolute_ttl:
            raise IdentityLifecycleError("idle expiry cannot exceed absolute expiry")

        raw_token = _opaque_token()
        session = Session(
            id=uuid4(),
            user_id=user_id,
            token_digest=_digest(raw_token),
            device_reference=device_reference,
            authentication_strength=authentication_strength,
            authenticated_at=now,
            created_at=now,
            idle_expires_at=now + idle_ttl,
            absolute_expires_at=now + absolute_ttl,
        )
        self._sessions[session.id] = session
        return session, raw_token

    def authenticate(
        self,
        raw_token: str,
        *,
        now: datetime,
        privileged: bool = False,
        recent_authentication: timedelta = timedelta(minutes=15),
    ) -> Session:
        """Resolve current state for one command/query without positive caching."""

        digest = _digest(raw_token)
        session = next(
            (
                candidate
                for candidate in self._sessions.values()
                if hmac.compare_digest(candidate.token_digest, digest)
            ),
            None,
        )
        if session is None:
            raise AuthenticationError("session is invalid")
        if session.revoked_at is not None:
            raise AuthenticationError("session is revoked")
        if now >= session.idle_expires_at:
            raise AuthenticationError("session idle expiry has elapsed")
        if now >= session.absolute_expires_at:
            raise AuthenticationError("session absolute expiry has elapsed")
        if privileged:
            if session.authentication_strength is not AuthenticationStrength.MFA:
                raise AuthenticationError("privileged operation requires MFA")
            if now - session.authenticated_at > recent_authentication:
                raise AuthenticationError(
                    "privileged operation requires recent authentication"
                )
        return session

    def revoke_session(self, session_id: UUID, *, now: datetime) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise AuthenticationError("session does not exist")
        self._sessions[session_id] = replace(session, revoked_at=now)

    def revoke_user_sessions(self, user_id: UUID, *, now: datetime) -> tuple[UUID, ...]:
        revoked: list[UUID] = []
        for session_id, session in tuple(self._sessions.items()):
            if session.user_id != user_id or session.revoked_at is not None:
                continue
            self._sessions[session_id] = replace(session, revoked_at=now)
            revoked.append(session_id)
        return tuple(revoked)


@dataclass(frozen=True, slots=True)
class Invitation:
    """Hashed, scoped, single-use invitation record."""

    id: UUID
    token_digest: str
    inviter_user_id: UUID
    organization_id: UUID
    workspace_id: UUID
    intended_email: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None


class InvitationStore:
    """Invitation lifecycle with authority and target-policy rechecks."""

    MAXIMUM_TTL = timedelta(hours=72)

    def __init__(self) -> None:
        self._invitations: dict[UUID, Invitation] = {}

    def issue(
        self,
        *,
        inviter_user_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        intended_email: str,
        now: datetime,
        ttl: timedelta = MAXIMUM_TTL,
    ) -> tuple[Invitation, str]:
        if ttl <= timedelta(0) or ttl > self.MAXIMUM_TTL:
            raise InvitationError("invitation expiry must be within 72 hours")
        raw_token = _opaque_token()
        invitation = Invitation(
            id=uuid4(),
            token_digest=_digest(raw_token),
            inviter_user_id=inviter_user_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            intended_email=intended_email.casefold(),
            created_at=now,
            expires_at=now + ttl,
        )
        self._invitations[invitation.id] = invitation
        return invitation, raw_token

    def accept(
        self,
        raw_token: str,
        *,
        claimant_email: str,
        now: datetime,
        inviter_is_authorized: bool,
        target_policy_allows: bool,
    ) -> Invitation:
        digest = _digest(raw_token)
        invitation = next(
            (
                candidate
                for candidate in self._invitations.values()
                if hmac.compare_digest(candidate.token_digest, digest)
            ),
            None,
        )
        if invitation is None:
            raise InvitationError("invitation is invalid")
        if invitation.accepted_at is not None:
            raise InvitationError("invitation is already used")
        if now >= invitation.expires_at:
            raise InvitationError("invitation is expired")
        if claimant_email.casefold() != invitation.intended_email:
            raise InvitationError("invitation email does not match")
        if not inviter_is_authorized:
            raise InvitationError("inviter authority is no longer valid")
        if not target_policy_allows:
            raise InvitationError("target membership policy rejected invitation")

        accepted = replace(invitation, accepted_at=now)
        self._invitations[invitation.id] = accepted
        return accepted


@dataclass(frozen=True, slots=True)
class RecoveryToken:
    """Hashed, expiring recovery credential."""

    id: UUID
    user_id: UUID
    token_digest: str
    expires_at: datetime
    invalidated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Security evidence emitted by a successful account recovery."""

    revoked_session_ids: tuple[UUID, ...]
    invalidated_recovery_token_ids: tuple[UUID, ...]
    events: tuple[str, ...]


class RecoveryService:
    """Recovery workflow that revokes all outstanding user credentials."""

    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions
        self._tokens: dict[UUID, RecoveryToken] = {}

    def issue(
        self,
        *,
        user_id: UUID,
        now: datetime,
        ttl: timedelta,
    ) -> tuple[RecoveryToken, str]:
        if ttl <= timedelta(0):
            raise RecoveryError("recovery token expiry must be in the future")
        raw_token = _opaque_token()
        token = RecoveryToken(
            id=uuid4(),
            user_id=user_id,
            token_digest=_digest(raw_token),
            expires_at=now + ttl,
        )
        self._tokens[token.id] = token
        return token, raw_token

    def complete(
        self,
        raw_token: str,
        *,
        now: datetime,
        recovery_channel_verified: bool,
        step_up_verified: bool,
    ) -> RecoveryResult:
        digest = _digest(raw_token)
        token = next(
            (
                candidate
                for candidate in self._tokens.values()
                if hmac.compare_digest(candidate.token_digest, digest)
            ),
            None,
        )
        if token is None or token.invalidated_at is not None:
            raise RecoveryError("recovery token is invalid")
        if now >= token.expires_at:
            raise RecoveryError("recovery token is expired")
        if not recovery_channel_verified:
            raise RecoveryError("verified recovery channel is required")
        if not step_up_verified:
            raise RecoveryError("step-up verification is required")

        invalidated: list[UUID] = []
        for token_id, candidate in tuple(self._tokens.items()):
            if candidate.user_id != token.user_id or candidate.invalidated_at is not None:
                continue
            self._tokens[token_id] = replace(candidate, invalidated_at=now)
            invalidated.append(token_id)

        revoked_sessions = self._sessions.revoke_user_sessions(token.user_id, now=now)
        return RecoveryResult(
            revoked_session_ids=revoked_sessions,
            invalidated_recovery_token_ids=tuple(invalidated),
            events=(
                "security.identity_recovery_notification",
                "audit.identity_recovery_completed",
            ),
        )


@dataclass(frozen=True, slots=True)
class ServicePrincipal:
    """Explicitly scoped and revocable non-human identity."""

    id: UUID
    owner_user_id: UUID
    workspace_id: UUID
    purpose: str
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.purpose.strip():
            raise IdentityLifecycleError("service principal purpose is required")

    def is_active(self, *, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at

    def revoke(self, *, now: datetime) -> ServicePrincipal:
        return replace(self, revoked_at=now)
