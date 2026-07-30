"""Transactional identity lifecycle service for H1-03."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.lifecycle_models import (
    IdentityLifecycleToken,
    IdentitySession,
    SecurityNotification,
)
from app.identity.models import ExternalIdentityLink, User
from app.tenancy.models import AuditEvent, OutboxEvent


class IdentityLifecycleError(ValueError):
    """Base class for a denied identity lifecycle operation."""


class InvalidLifecycleTokenError(IdentityLifecycleError):
    """Raised for missing, expired, replayed, revoked, or wrong-purpose tokens."""


class InvalidSessionError(IdentityLifecycleError):
    """Raised when a session is missing, expired, revoked, or otherwise invalid."""


class StrongAuthenticationRequiredError(IdentityLifecycleError):
    """Raised when identity linking lacks recent MFA-backed authentication."""


@dataclass(frozen=True, slots=True)
class SessionCookiePolicy:
    """Required browser cookie controls for opaque Atlas sessions."""

    name: str = "__Host-atlas_session"
    secure: bool = True
    http_only: bool = True
    same_site: str = "lax"
    path: str = "/"


@dataclass(frozen=True, slots=True)
class IssuedSecret:
    """Raw secret returned once alongside its durable record identity."""

    record_id: uuid.UUID
    raw_secret: str


def hash_secret(raw_secret: str) -> str:
    """Return the only representation of a secret allowed in persistence."""

    if len(raw_secret) < 32:
        raise IdentityLifecycleError("identity secret must contain at least 32 characters")
    return hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()


def validate_csrf(cookie_token: str | None, header_token: str | None) -> None:
    """Validate a double-submit CSRF token without timing-sensitive comparison."""

    if not cookie_token or not header_token or not hmac.compare_digest(
        cookie_token,
        header_token,
    ):
        raise InvalidSessionError("CSRF validation failed")


class IdentityLifecycleService:
    """Execute H1-03 lifecycle changes in the caller's database transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue_session(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        device_id: str,
        authentication_strength: str,
        expires_at: datetime,
        now: datetime | None = None,
        mfa_authenticated_at: datetime | None = None,
    ) -> IssuedSecret:
        issued_at = now or datetime.now(UTC)
        if expires_at <= issued_at:
            raise IdentityLifecycleError("session expiry must be in the future")
        user = await self._session.get(User, user_id)
        if user is None or user.status != "active":
            raise InvalidSessionError("active user is required")
        if user.mfa_required and authentication_strength != "mfa":
            raise StrongAuthenticationRequiredError("MFA is required")
        if authentication_strength == "mfa" and mfa_authenticated_at is None:
            raise StrongAuthenticationRequiredError("MFA evidence is required")

        raw_secret = secrets.token_urlsafe(48)
        identity_session = IdentitySession(
            workspace_id=workspace_id,
            user_id=user_id,
            token_hash=hash_secret(raw_secret),
            device_id=device_id,
            authentication_strength=authentication_strength,
            authenticated_at=issued_at,
            mfa_authenticated_at=mfa_authenticated_at,
            last_seen_at=issued_at,
            expires_at=expires_at,
        )
        self._session.add(identity_session)
        await self._session.flush()
        await self._record_event(
            workspace_id=workspace_id,
            user_id=user_id,
            action="identity.session_issued",
            target_type="identity_session",
            target_id=identity_session.id,
            payload={"authentication_strength": authentication_strength},
        )
        return IssuedSecret(identity_session.id, raw_secret)

    async def authenticate_session(
        self,
        *,
        workspace_id: uuid.UUID,
        raw_secret: str,
        now: datetime | None = None,
    ) -> IdentitySession:
        checked_at = now or datetime.now(UTC)
        identity_session = await self._session.scalar(
            select(IdentitySession)
            .where(
                IdentitySession.workspace_id == workspace_id,
                IdentitySession.token_hash == hash_secret(raw_secret),
            )
            .with_for_update()
        )
        if (
            identity_session is None
            or identity_session.revoked_at is not None
            or identity_session.expires_at <= checked_at
        ):
            raise InvalidSessionError("session is invalid")
        user = await self._session.get(User, identity_session.user_id)
        if user is None or user.status != "active":
            raise InvalidSessionError("identity is invalid")
        identity_session.last_seen_at = checked_at
        await self._session.flush()
        return identity_session

    async def revoke_session(
        self,
        *,
        workspace_id: uuid.UUID,
        session_id: uuid.UUID,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        revoked_at = now or datetime.now(UTC)
        identity_session = await self._session.scalar(
            select(IdentitySession)
            .where(
                IdentitySession.workspace_id == workspace_id,
                IdentitySession.id == session_id,
            )
            .with_for_update()
        )
        if identity_session is None:
            raise InvalidSessionError("session does not exist")
        if identity_session.revoked_at is not None:
            return
        identity_session.revoked_at = revoked_at
        identity_session.revocation_reason = reason
        await self._record_event(
            workspace_id=workspace_id,
            user_id=identity_session.user_id,
            action="identity.session_revoked",
            target_type="identity_session",
            target_id=identity_session.id,
            payload={"reason": reason},
        )

    async def rotate_session(
        self,
        *,
        workspace_id: uuid.UUID,
        raw_secret: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> IssuedSecret:
        rotated_at = now or datetime.now(UTC)
        current = await self.authenticate_session(
            workspace_id=workspace_id,
            raw_secret=raw_secret,
            now=rotated_at,
        )
        await self.revoke_session(
            workspace_id=workspace_id,
            session_id=current.id,
            reason="rotated",
            now=rotated_at,
        )
        return await self.issue_session(
            workspace_id=workspace_id,
            user_id=current.user_id,
            device_id=current.device_id,
            authentication_strength=current.authentication_strength,
            expires_at=expires_at,
            now=rotated_at,
            mfa_authenticated_at=current.mfa_authenticated_at,
        )

    async def issue_lifecycle_token(
        self,
        *,
        workspace_id: uuid.UUID,
        purpose: str,
        expires_at: datetime,
        scope: dict[str, object],
        user_id: uuid.UUID | None = None,
        issued_by_user_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> IssuedSecret:
        issued_at = now or datetime.now(UTC)
        if purpose not in {"invitation", "recovery"}:
            raise IdentityLifecycleError("unsupported lifecycle token purpose")
        if expires_at <= issued_at:
            raise IdentityLifecycleError("token expiry must be in the future")
        if purpose == "invitation" and expires_at > issued_at + timedelta(hours=72):
            raise IdentityLifecycleError("invitation expiry cannot exceed 72 hours")
        if purpose == "recovery" and user_id is None:
            raise IdentityLifecycleError("recovery token requires a user")
        if purpose == "invitation" and "authority_version" not in scope:
            raise IdentityLifecycleError("invitation requires authority version")

        raw_secret = secrets.token_urlsafe(48)
        token = IdentityLifecycleToken(
            workspace_id=workspace_id,
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_secret(raw_secret),
            scope=scope,
            issued_by_user_id=issued_by_user_id,
            expires_at=expires_at,
        )
        self._session.add(token)
        await self._session.flush()
        return IssuedSecret(token.id, raw_secret)

    async def consume_lifecycle_token(
        self,
        *,
        workspace_id: uuid.UUID,
        raw_secret: str,
        expected_purpose: str,
        current_authority_version: str | None = None,
        now: datetime | None = None,
    ) -> IdentityLifecycleToken:
        consumed_at = now or datetime.now(UTC)
        token = await self._session.scalar(
            select(IdentityLifecycleToken)
            .where(
                IdentityLifecycleToken.workspace_id == workspace_id,
                IdentityLifecycleToken.token_hash == hash_secret(raw_secret),
            )
            .with_for_update()
        )
        if (
            token is None
            or token.purpose != expected_purpose
            or token.expires_at <= consumed_at
            or token.consumed_at is not None
            or token.revoked_at is not None
        ):
            raise InvalidLifecycleTokenError("lifecycle token is invalid")
        if expected_purpose == "invitation" and (
            current_authority_version is None
            or token.scope.get("authority_version") != current_authority_version
        ):
            raise InvalidLifecycleTokenError("invitation authority changed")
        token.consumed_at = consumed_at
        await self._session.flush()
        return token

    async def revoke_lifecycle_token(
        self,
        *,
        workspace_id: uuid.UUID,
        token_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        now: datetime | None = None,
    ) -> None:
        revoked_at = now or datetime.now(UTC)
        token = await self._session.scalar(
            select(IdentityLifecycleToken)
            .where(
                IdentityLifecycleToken.workspace_id == workspace_id,
                IdentityLifecycleToken.id == token_id,
            )
            .with_for_update()
        )
        if token is None:
            raise InvalidLifecycleTokenError("lifecycle token does not exist")
        if token.revoked_at is not None:
            return
        token.revoked_at = revoked_at
        await self._record_event(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            action="identity.lifecycle_token_revoked",
            target_type="identity_lifecycle_token",
            target_id=token.id,
            payload={"purpose": token.purpose},
        )

    async def recover_account(
        self,
        *,
        workspace_id: uuid.UUID,
        raw_secret: str,
        now: datetime | None = None,
    ) -> uuid.UUID:
        recovered_at = now or datetime.now(UTC)
        token = await self.consume_lifecycle_token(
            workspace_id=workspace_id,
            raw_secret=raw_secret,
            expected_purpose="recovery",
            now=recovered_at,
        )
        if token.user_id is None:
            raise InvalidLifecycleTokenError("recovery token has no identity")
        await self._session.execute(
            update(IdentitySession)
            .where(
                IdentitySession.workspace_id == workspace_id,
                IdentitySession.user_id == token.user_id,
                IdentitySession.revoked_at.is_(None),
            )
            .values(
                revoked_at=recovered_at,
                revocation_reason="account_recovery",
            )
        )
        await self._session.execute(
            update(IdentityLifecycleToken)
            .where(
                IdentityLifecycleToken.workspace_id == workspace_id,
                IdentityLifecycleToken.user_id == token.user_id,
                IdentityLifecycleToken.purpose == "recovery",
                IdentityLifecycleToken.consumed_at.is_(None),
                IdentityLifecycleToken.revoked_at.is_(None),
            )
            .values(revoked_at=recovered_at)
        )
        notification = SecurityNotification(
            workspace_id=workspace_id,
            user_id=token.user_id,
            event_type="identity.account_recovered",
            payload={"recovery_token_id": str(token.id)},
        )
        self._session.add(notification)
        await self._session.flush()
        await self._record_event(
            workspace_id=workspace_id,
            user_id=token.user_id,
            action="identity.account_recovered",
            target_type="user",
            target_id=token.user_id,
            payload={"notification_id": str(notification.id)},
        )
        return token.user_id

    async def begin_identity_link_review(
        self,
        *,
        workspace_id: uuid.UUID,
        external_identity_id: uuid.UUID,
        session_id: uuid.UUID,
        proof_reference: str,
        review_expires_at: datetime,
        now: datetime | None = None,
    ) -> None:
        proofed_at = now or datetime.now(UTC)
        if review_expires_at <= proofed_at:
            raise IdentityLifecycleError("identity-link review expiry must be in the future")
        identity_session = await self._session.scalar(
            select(IdentitySession).where(
                IdentitySession.workspace_id == workspace_id,
                IdentitySession.id == session_id,
            )
        )
        if (
            identity_session is None
            or identity_session.revoked_at is not None
            or identity_session.expires_at <= proofed_at
            or identity_session.authentication_strength != "mfa"
            or identity_session.mfa_authenticated_at is None
            or proofed_at - identity_session.mfa_authenticated_at > timedelta(minutes=15)
            or not proof_reference.strip()
        ):
            raise StrongAuthenticationRequiredError(
                "recent MFA and proof of both identities are required"
            )
        link = await self._session.get(ExternalIdentityLink, external_identity_id)
        if link is None or link.user_id != identity_session.user_id:
            raise IdentityLifecycleError("external identity does not match session")
        link.status = "review_pending"
        link.proofed_at = proofed_at
        link.proof_reference = proof_reference
        link.review_expires_at = review_expires_at
        link.version += 1
        await self._record_event(
            workspace_id=workspace_id,
            user_id=link.user_id,
            action="identity.link_review_started",
            target_type="external_identity_link",
            target_id=link.id,
            payload={"review_expires_at": review_expires_at.isoformat()},
        )

    async def _record_event(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        target_type: str,
        target_id: uuid.UUID,
        payload: dict[str, object],
    ) -> None:
        event_id = uuid.uuid4()
        self._session.add(
            AuditEvent(
                workspace_id=workspace_id,
                id=event_id,
                actor_type="user",
                actor_id=user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome="success",
                details=payload,
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=workspace_id,
                id=uuid.uuid4(),
                event_type=action,
                aggregate_type="identity_lifecycle_event",
                aggregate_id=event_id,
                aggregate_sequence=1,
                payload={
                    "event_id": str(event_id),
                    "target_type": target_type,
                    "target_id": str(target_id),
                    **payload,
                },
            )
        )
        await self._session.flush()
