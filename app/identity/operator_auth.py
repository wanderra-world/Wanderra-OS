"""Canonical external-identity to workspace-session authentication boundary."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization.repository import AuthorizationRepository
from app.identity.lifecycle import IdentityLifecycleService
from app.identity.models import ExternalIdentityLink, User
from app.memberships.models import WorkspaceMembership
from app.memberships.repository import WorkspaceMembershipRepository
from app.tenancy.models import AuditEvent, OutboxEvent, Workspace

OPERATOR_LOGIN_PERMISSION = "manage_workspace"
OPERATOR_SESSION_LIFETIME = timedelta(hours=12)


class OperatorAuthenticationError(RuntimeError):
    """Fail-closed authentication error without identity or secret disclosure."""


@dataclass(frozen=True, slots=True)
class VerifiedExternalIdentity:
    """Provider-neutral identity proven by an accepted external authority adapter."""

    issuer: str
    subject: str
    email: str
    email_verified: bool


class OperatorIdentityRepositoryPort(Protocol):
    async def resolve_identity(
        self, *, issuer: str, subject: str
    ) -> tuple[ExternalIdentityLink, User] | tuple[None, None]: ...

    async def workspace_for_login(self, workspace_id: uuid.UUID) -> Workspace | None: ...

    async def membership_for_login(
        self, *, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> WorkspaceMembership | None: ...

    async def role_permission_effects(
        self, *, role_key: str, role_version: int
    ) -> frozenset[str]: ...


@dataclass(frozen=True, slots=True, repr=False)
class OperatorSessionGrant:
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    session_id: uuid.UUID
    raw_session: str
    csrf_token: str
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            "OperatorSessionGrant("
            f"workspace_id={self.workspace_id!r}, user_id={self.user_id!r}, "
            f"membership_id={self.membership_id!r}, session_id={self.session_id!r}, "
            "raw_session=<redacted>, csrf_token=<redacted>, "
            f"expires_at={self.expires_at!r})"
        )


class OperatorSessionIssuerPort(Protocol):
    async def issue(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        device_id: str,
        expires_at: datetime,
        now: datetime,
    ) -> OperatorSessionGrant: ...


class OperatorIdentityRepository:
    """Read only accepted canonical identity, membership, and RBAC records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._memberships = WorkspaceMembershipRepository(session)
        self._authorization = AuthorizationRepository(session)

    async def resolve_identity(
        self, *, issuer: str, subject: str
    ) -> tuple[ExternalIdentityLink, User] | tuple[None, None]:
        row = (
            await self._session.execute(
                select(ExternalIdentityLink, User)
                .join(User, User.id == ExternalIdentityLink.user_id)
                .where(
                    ExternalIdentityLink.issuer == issuer,
                    ExternalIdentityLink.subject == subject,
                )
            )
        ).one_or_none()
        return row if row is not None else (None, None)

    async def workspace_for_login(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def membership_for_login(
        self, *, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> WorkspaceMembership | None:
        return await self._memberships.get_by_user(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    async def role_permission_effects(
        self, *, role_key: str, role_version: int
    ) -> frozenset[str]:
        permission = await self._authorization.get_permission(
            permission_key=OPERATOR_LOGIN_PERMISSION,
            permission_version=1,
        )
        if permission is None or not permission.active:
            return frozenset()
        return await self._authorization.list_role_permission_effects(
            role_key=role_key,
            role_version=role_version,
            permission_key=OPERATOR_LOGIN_PERMISSION,
            permission_version=permission.version,
        )


class AtlasOperatorSessionIssuer:
    """Issue only the existing Atlas session after authentication gates succeed."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        device_id: str,
        expires_at: datetime,
        now: datetime,
    ) -> OperatorSessionGrant:
        issued = await IdentityLifecycleService(self._session).issue_session(
            workspace_id=workspace_id,
            user_id=user_id,
            device_id=device_id,
            authentication_strength="oidc",
            expires_at=expires_at,
            now=now,
        )
        audit_id = uuid.uuid4()
        details = {
            "authentication_method": "google_oidc",
            "membership_id": str(membership_id),
        }
        self._session.add(
            AuditEvent(
                workspace_id=workspace_id,
                id=audit_id,
                actor_type="user",
                actor_id=user_id,
                action="identity.operator_authenticated",
                target_type="identity_session",
                target_id=issued.record_id,
                outcome="success",
                details=details,
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=workspace_id,
                id=uuid.uuid4(),
                event_type="identity.operator_authenticated",
                aggregate_type="identity_session",
                aggregate_id=issued.record_id,
                aggregate_sequence=1,
                actor_id=user_id,
                payload={"audit_event_id": str(audit_id), **details},
            )
        )
        await self._session.flush()
        return OperatorSessionGrant(
            workspace_id=workspace_id,
            user_id=user_id,
            membership_id=membership_id,
            session_id=issued.record_id,
            raw_session=issued.raw_secret,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=expires_at,
        )


class OperatorAuthenticationService:
    """Map a verified external subject to one authorized workspace session."""

    def __init__(
        self,
        repository: OperatorIdentityRepositoryPort,
        session_issuer: OperatorSessionIssuerPort,
    ) -> None:
        self._repository = repository
        self._session_issuer = session_issuer

    @classmethod
    def for_session(cls, session: AsyncSession) -> OperatorAuthenticationService:
        return cls(OperatorIdentityRepository(session), AtlasOperatorSessionIssuer(session))

    async def authenticate(
        self,
        *,
        claims: VerifiedExternalIdentity,
        workspace_id: uuid.UUID,
        device_id: str,
        now: datetime | None = None,
    ) -> OperatorSessionGrant:
        authenticated_at = now or datetime.now(UTC)
        link, user = await self._repository.resolve_identity(
            issuer=claims.issuer,
            subject=claims.subject,
        )
        if (
            link is None
            or user is None
            or link.status != "active"
            or user.status != "active"
            or link.user_id != user.id
        ):
            raise OperatorAuthenticationError("operator identity is unavailable")
        workspace = await self._repository.workspace_for_login(workspace_id)
        if workspace is None or workspace.status != "active":
            raise OperatorAuthenticationError("operator workspace is unavailable")
        membership = await self._repository.membership_for_login(
            workspace_id=workspace_id,
            user_id=user.id,
        )
        if (
            membership is None
            or membership.status != "active"
            or membership.workspace_id != workspace_id
            or membership.organization_id != workspace.organization_id
            or membership.user_id != user.id
        ):
            raise OperatorAuthenticationError("operator membership is unavailable")
        effects = await self._repository.role_permission_effects(
            role_key=membership.role_key,
            role_version=membership.role_version,
        )
        if "deny" in effects or "allow" not in effects:
            raise OperatorAuthenticationError("operator authorization is denied")
        normalized_device = device_id.strip()
        if not normalized_device or len(normalized_device) > 255:
            raise OperatorAuthenticationError("operator device is invalid")
        return await self._session_issuer.issue(
            workspace_id=workspace_id,
            user_id=user.id,
            membership_id=membership.id,
            device_id=normalized_device,
            expires_at=authenticated_at + OPERATOR_SESSION_LIFETIME,
            now=authenticated_at,
        )
