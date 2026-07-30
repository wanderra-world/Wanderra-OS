"""Transactional workspace membership lifecycle for H1-04."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.lifecycle import IdentityLifecycleService, IssuedSecret
from app.identity.models import User
from app.memberships.contracts import (
    MEMBERSHIP_ROLE_VERSION,
    WORKSPACE_MEMBERSHIP_ROLES,
    MembershipLifecycleError,
)
from app.memberships.models import FixedMembershipRole, WorkspaceMembership
from app.memberships.repository import WorkspaceMembershipRepository
from app.tenancy.models import AuditEvent, OutboxEvent, Workspace


class WorkspaceMembershipService:
    """Execute membership transitions in the caller's database transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = WorkspaceMembershipRepository(session)
        self._identity_lifecycle = IdentityLifecycleService(session)

    async def invite(
        self,
        *,
        workspace_id: uuid.UUID,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role_key: str,
        invited_by_user_id: uuid.UUID,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> IssuedSecret:
        invited_at = now or datetime.now(UTC)
        await self._lock_workspace(workspace_id, organization_id)
        await self._validate_user(user_id)
        await self._validate_workspace_role(role_key)
        membership = await self._repository.get_by_user(
            workspace_id=workspace_id,
            user_id=user_id,
            for_update=True,
        )
        if membership is None:
            membership = WorkspaceMembership(
                workspace_id=workspace_id,
                organization_id=organization_id,
                user_id=user_id,
                role_key=role_key,
                role_version=MEMBERSHIP_ROLE_VERSION,
                status="invited",
                version=1,
                invited_by_user_id=invited_by_user_id,
                origin="invitation",
            )
            await self._repository.add(membership)
        elif membership.status != "revoked":
            raise MembershipLifecycleError("user already has a workspace membership")
        else:
            membership.role_key = role_key
            membership.role_version = MEMBERSHIP_ROLE_VERSION
            membership.status = "invited"
            membership.version += 1
            membership.invited_by_user_id = invited_by_user_id
            membership.invitation_token_id = None
            membership.accepted_invitation_token_id = None
            membership.activated_at = None
            membership.suspended_at = None
            membership.revoked_at = None
            membership.revocation_reason = None
            membership.origin = "invitation"
            await self._session.flush()

        invitation = await self._identity_lifecycle.issue_lifecycle_token(
            workspace_id=workspace_id,
            purpose="invitation",
            expires_at=expires_at,
            user_id=user_id,
            issued_by_user_id=invited_by_user_id,
            scope={
                "authority_version": str(membership.version),
                "membership_id": str(membership.id),
                "organization_id": str(organization_id),
                "workspace_id": str(workspace_id),
                "user_id": str(user_id),
                "role_key": role_key,
                "role_version": MEMBERSHIP_ROLE_VERSION,
            },
            now=invited_at,
        )
        membership.invitation_token_id = invitation.record_id
        await self._record_event(
            membership=membership,
            actor_user_id=invited_by_user_id,
            action="membership.invited",
        )
        return invitation

    async def accept_invitation(
        self,
        *,
        workspace_id: uuid.UUID,
        raw_secret: str,
        user_id: uuid.UUID,
        now: datetime | None = None,
    ) -> WorkspaceMembership:
        accepted_at = now or datetime.now(UTC)
        token = await self._identity_lifecycle.consume_lifecycle_token(
            workspace_id=workspace_id,
            raw_secret=raw_secret,
            expected_purpose="invitation",
            current_authority_version=str(
                await self._invitation_authority_version(
                    workspace_id=workspace_id,
                    raw_secret=raw_secret,
                )
            ),
            now=accepted_at,
        )
        membership_id = self._scope_uuid(token.scope, "membership_id")
        membership = await self._repository.get(
            workspace_id=workspace_id,
            membership_id=membership_id,
            for_update=True,
        )
        if (
            membership is None
            or membership.status != "invited"
            or membership.user_id != user_id
            or token.user_id != user_id
            or membership.invitation_token_id != token.id
            or token.scope.get("workspace_id") != str(workspace_id)
            or token.scope.get("organization_id") != str(membership.organization_id)
            or token.scope.get("role_key") != membership.role_key
            or token.scope.get("role_version") != membership.role_version
            or token.scope.get("authority_version") != str(membership.version)
        ):
            raise MembershipLifecycleError("invitation does not match membership")
        membership.status = "active"
        membership.activated_at = accepted_at
        membership.accepted_invitation_token_id = token.id
        membership.version += 1
        await self._record_event(
            membership=membership,
            actor_user_id=user_id,
            action="membership.invitation_accepted",
        )
        return membership

    async def create_active(
        self,
        *,
        workspace_id: uuid.UUID,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role_key: str,
        actor_user_id: uuid.UUID,
        now: datetime | None = None,
    ) -> WorkspaceMembership:
        activated_at = now or datetime.now(UTC)
        await self._lock_workspace(workspace_id, organization_id)
        await self._validate_user(user_id)
        await self._validate_workspace_role(role_key)
        if (
            await self._repository.get_by_user(
                workspace_id=workspace_id,
                user_id=user_id,
                for_update=True,
            )
            is not None
        ):
            raise MembershipLifecycleError("user already has a workspace membership")
        membership = await self._repository.add(
            WorkspaceMembership(
                workspace_id=workspace_id,
                organization_id=organization_id,
                user_id=user_id,
                role_key=role_key,
                role_version=MEMBERSHIP_ROLE_VERSION,
                status="active",
                version=1,
                activated_at=activated_at,
                origin="direct",
            )
        )
        await self._record_event(
            membership=membership,
            actor_user_id=actor_user_id,
            action="membership.created",
        )
        return membership

    async def change_role(
        self,
        *,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        role_key: str,
        actor_user_id: uuid.UUID,
    ) -> WorkspaceMembership:
        await self._validate_workspace_role(role_key)
        membership = await self._require_membership(workspace_id, membership_id)
        await self._lock_workspace(workspace_id, membership.organization_id)
        if membership.status != "active":
            raise MembershipLifecycleError("only active memberships can change role")
        if membership.role_key == "workspace_owner" and role_key != "workspace_owner":
            await self._require_additional_active_owner(workspace_id, membership.id)
        membership.role_key = role_key
        membership.role_version = MEMBERSHIP_ROLE_VERSION
        membership.version += 1
        await self._record_event(
            membership=membership,
            actor_user_id=actor_user_id,
            action="membership.role_changed",
        )
        return membership

    async def set_status(
        self,
        *,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        status: str,
        actor_user_id: uuid.UUID,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> WorkspaceMembership:
        changed_at = now or datetime.now(UTC)
        membership = await self._require_membership(workspace_id, membership_id)
        await self._lock_workspace(workspace_id, membership.organization_id)
        allowed = {
            "active": {"suspended", "revoked"},
            "suspended": {"active", "revoked"},
            "invited": {"revoked"},
            "revoked": set(),
        }
        if status not in allowed[membership.status]:
            raise MembershipLifecycleError("membership status transition is invalid")
        if (
            membership.role_key == "workspace_owner"
            and membership.status == "active"
            and status != "active"
        ):
            await self._require_additional_active_owner(workspace_id, membership.id)
        membership.status = status
        membership.version += 1
        if status == "suspended":
            membership.suspended_at = changed_at
        elif status == "active":
            membership.suspended_at = None
        elif status == "revoked":
            membership.revoked_at = changed_at
            membership.revocation_reason = reason or "revoked"
        await self._record_event(
            membership=membership,
            actor_user_id=actor_user_id,
            action=f"membership.{status}",
        )
        return membership

    async def _invitation_authority_version(
        self,
        *,
        workspace_id: uuid.UUID,
        raw_secret: str,
    ) -> int:
        from app.identity.lifecycle import hash_secret
        from app.identity.lifecycle_models import IdentityLifecycleToken

        token = await self._session.scalar(
            select(IdentityLifecycleToken).where(
                IdentityLifecycleToken.workspace_id == workspace_id,
                IdentityLifecycleToken.token_hash == hash_secret(raw_secret),
            )
        )
        if token is None:
            raise MembershipLifecycleError("invitation does not exist")
        membership_id = self._scope_uuid(token.scope, "membership_id")
        membership = await self._repository.get(
            workspace_id=workspace_id,
            membership_id=membership_id,
        )
        if membership is None:
            raise MembershipLifecycleError("invitation membership does not exist")
        return membership.version

    async def _require_membership(
        self,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
    ) -> WorkspaceMembership:
        membership = await self._repository.get(
            workspace_id=workspace_id,
            membership_id=membership_id,
            for_update=True,
        )
        if membership is None:
            raise MembershipLifecycleError("workspace membership does not exist")
        return membership

    async def _lock_workspace(
        self,
        workspace_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Workspace:
        workspace = await self._session.scalar(
            select(Workspace)
            .where(
                Workspace.id == workspace_id,
                Workspace.organization_id == organization_id,
            )
            .with_for_update()
        )
        if workspace is None:
            raise MembershipLifecycleError("workspace and organization do not match")
        return workspace

    async def _validate_user(self, user_id: uuid.UUID) -> None:
        user = await self._session.get(User, user_id)
        if user is None or user.status != "active":
            raise MembershipLifecycleError("active user is required")

    async def _validate_workspace_role(self, role_key: str) -> None:
        if role_key not in WORKSPACE_MEMBERSHIP_ROLES:
            raise MembershipLifecycleError("workspace role is invalid")
        role = await self._session.get(
            FixedMembershipRole,
            (role_key, MEMBERSHIP_ROLE_VERSION),
        )
        if role is None or role.scope != "workspace" or not role.active:
            raise MembershipLifecycleError("workspace role definition is unavailable")

    async def _require_additional_active_owner(
        self,
        workspace_id: uuid.UUID,
        excluded_membership_id: uuid.UUID,
    ) -> None:
        count = await self._session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.id != excluded_membership_id,
                WorkspaceMembership.role_key == "workspace_owner",
                WorkspaceMembership.status == "active",
            )
        )
        if not count:
            raise MembershipLifecycleError(
                "workspace must retain at least one active owner"
            )

    @staticmethod
    def _scope_uuid(scope: dict[str, object], key: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(scope[key]))
        except (KeyError, TypeError, ValueError) as error:
            raise MembershipLifecycleError("invitation scope is invalid") from error

    async def _record_event(
        self,
        *,
        membership: WorkspaceMembership,
        actor_user_id: uuid.UUID,
        action: str,
    ) -> None:
        audit_id = uuid.uuid4()
        payload = {
            "membership_id": str(membership.id),
            "organization_id": str(membership.organization_id),
            "user_id": str(membership.user_id),
            "role_key": membership.role_key,
            "role_version": membership.role_version,
            "status": membership.status,
            "membership_version": membership.version,
        }
        self._session.add(
            AuditEvent(
                workspace_id=membership.workspace_id,
                id=audit_id,
                actor_type="user",
                actor_id=actor_user_id,
                action=action,
                target_type="workspace_membership",
                target_id=membership.id,
                outcome="success",
                details=payload,
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=membership.workspace_id,
                id=uuid.uuid4(),
                event_type=action,
                aggregate_type="membership_lifecycle_event",
                aggregate_id=audit_id,
                aggregate_sequence=1,
                payload={"audit_event_id": str(audit_id), **payload},
            )
        )
        await self._session.flush()
