"""One-time ADR-036 initial external-identity bootstrap service."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import ExternalIdentityLink, User
from app.memberships.models import WorkspaceMembership
from app.tenancy.models import AuditEvent, Workspace

FIXED_BOOTSTRAP_USER_ID = uuid.UUID("d34c44c9-1ada-43ad-ad70-5ae9568df146")
FIXED_BOOTSTRAP_WORKSPACE_ID = uuid.UUID("874fc276-27be-557d-cd2c-179bed466907")
NORMALIZED_GOOGLE_ISSUER = "https://accounts.google.com"


class BootstrapIdentityError(RuntimeError):
    """Raised when the bounded bootstrap cannot safely proceed."""


@dataclass(frozen=True, slots=True, repr=False)
class BootstrapIdentity:
    """Minimal verified Google identity retained after OIDC verification."""

    issuer: str
    subject: str
    audience: str
    verified_at: datetime

    def __post_init__(self) -> None:
        if self.issuer != NORMALIZED_GOOGLE_ISSUER:
            raise BootstrapIdentityError("bootstrap issuer is not normalized Google")
        if not self.subject.strip() or len(self.subject) > 255:
            raise BootstrapIdentityError("bootstrap subject is invalid")
        if not self.audience.strip():
            raise BootstrapIdentityError("bootstrap audience is required")
        if self.verified_at.tzinfo is None:
            raise BootstrapIdentityError("bootstrap verification time must be aware")

    @property
    def subject_fingerprint(self) -> str:
        return hashlib.sha256(self.subject.encode()).hexdigest()

    def __repr__(self) -> str:
        return (
            "BootstrapIdentity("
            f"issuer={self.issuer!r}, subject=<redacted>, "
            f"audience={self.audience!r}, verified_at={self.verified_at!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class BootstrapApproval:
    """Exact second approval binding one verified identity to the fixed target."""

    reference: str
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    issuer: str
    subject: str

    def __post_init__(self) -> None:
        if not self.reference.strip() or len(self.reference) > 128:
            raise BootstrapIdentityError("bootstrap approval reference is invalid")

    def authorizes(self, identity: BootstrapIdentity) -> bool:
        return (
            self.user_id == FIXED_BOOTSTRAP_USER_ID
            and self.workspace_id == FIXED_BOOTSTRAP_WORKSPACE_ID
            and self.issuer == identity.issuer
            and self.subject == identity.subject
        )

    def __repr__(self) -> str:
        return (
            "BootstrapApproval("
            f"reference={self.reference!r}, user_id={self.user_id!r}, "
            f"workspace_id={self.workspace_id!r}, issuer={self.issuer!r}, "
            "subject=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class BootstrapCommitResult:
    external_identity_link_id: uuid.UUID
    audit_event_id: uuid.UUID


class BootstrapIdentityLinkService:
    """Create the first link once, after verified identity and exact approval."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def require_ready(self, *, lock: bool = False) -> WorkspaceMembership:
        user_query = select(User).where(User.id == FIXED_BOOTSTRAP_USER_ID)
        if lock:
            user_query = user_query.with_for_update()
        user = await self._session.scalar(user_query)
        if user is None or user.status != "active":
            raise BootstrapIdentityError("fixed canonical user is unavailable")

        workspace = await self._session.get(Workspace, FIXED_BOOTSTRAP_WORKSPACE_ID)
        if workspace is None or workspace.status != "active":
            raise BootstrapIdentityError("fixed workspace is unavailable")

        membership = await self._session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == FIXED_BOOTSTRAP_WORKSPACE_ID,
                WorkspaceMembership.user_id == FIXED_BOOTSTRAP_USER_ID,
            )
        )
        if (
            membership is None
            or membership.status != "active"
            or membership.role_key != "workspace_owner"
            or membership.role_version != 1
        ):
            raise BootstrapIdentityError("fixed workspace ownership is unavailable")

        link_count = await self._session.scalar(
            select(func.count()).select_from(ExternalIdentityLink)
        )
        if link_count != 0:
            raise BootstrapIdentityError("identity bootstrap is already disabled")
        return membership

    async def commit(
        self,
        *,
        identity: BootstrapIdentity,
        approval: BootstrapApproval,
    ) -> BootstrapCommitResult:
        if not approval.authorizes(identity):
            raise BootstrapIdentityError("exact bootstrap approval does not match")
        await self.require_ready(lock=True)

        link_id = uuid.uuid4()
        audit_id = uuid.uuid4()
        self._session.add(
            ExternalIdentityLink(
                id=link_id,
                user_id=FIXED_BOOTSTRAP_USER_ID,
                issuer=identity.issuer,
                subject=identity.subject,
                email=None,
                email_verified=False,
                status="active",
                version=1,
            )
        )
        self._session.add(
            AuditEvent(
                workspace_id=FIXED_BOOTSTRAP_WORKSPACE_ID,
                id=audit_id,
                actor_type="system",
                actor_id=FIXED_BOOTSTRAP_USER_ID,
                action="identity.initial_external_link_bootstrapped",
                target_type="external_identity_link",
                target_id=link_id,
                outcome="success",
                details={
                    "approval_reference": approval.reference,
                    "issuer": identity.issuer,
                    "subject_fingerprint": identity.subject_fingerprint,
                    "audience": identity.audience,
                    "verified_at": identity.verified_at.isoformat(),
                    "ceremony": "adr_036_one_time_bootstrap",
                },
                correlation_id=approval.reference,
                classification="confidential",
            )
        )
        await self._session.flush()
        return BootstrapCommitResult(
            external_identity_link_id=link_id,
            audit_event_id=audit_id,
        )
