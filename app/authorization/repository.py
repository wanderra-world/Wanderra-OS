"""Database lookups for fixed-role authorization."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization.models import Permission, RolePermission
from app.identity.lifecycle_models import IdentitySession
from app.identity.models import User
from app.memberships.models import WorkspaceMembership


class AuthorizationRepository:
    """Perform uncached, workspace-explicit authorization lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_actor(self, actor_id: uuid.UUID) -> User | None:
        return await self.session.get(User, actor_id)

    async def get_session(
        self,
        *,
        workspace_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> IdentitySession | None:
        return await self.session.get(IdentitySession, (workspace_id, session_id))

    async def get_membership(
        self,
        *,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
    ) -> WorkspaceMembership | None:
        return await self.session.get(
            WorkspaceMembership,
            (workspace_id, membership_id),
        )

    async def get_permission(
        self,
        *,
        permission_key: str,
        permission_version: int,
    ) -> Permission | None:
        return await self.session.get(
            Permission,
            (permission_key, permission_version),
        )

    async def list_role_permission_effects(
        self,
        *,
        role_key: str,
        role_version: int,
        permission_key: str,
        permission_version: int,
    ) -> frozenset[str]:
        effects = await self.session.scalars(
            select(RolePermission.effect).where(
                RolePermission.role_key == role_key,
                RolePermission.role_version == role_version,
                RolePermission.permission_key == permission_key,
                RolePermission.permission_version == permission_version,
            )
        )
        return frozenset(effects)
