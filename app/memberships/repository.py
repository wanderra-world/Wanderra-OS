"""RLS-compatible repository for workspace memberships."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memberships.models import WorkspaceMembership


class WorkspaceMembershipRepository:
    """Persist and lock membership rows without making authorization decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def get(
        self,
        *,
        workspace_id: uuid.UUID,
        membership_id: uuid.UUID,
        for_update: bool = False,
    ) -> WorkspaceMembership | None:
        statement = select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.id == membership_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_by_user(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        for_update: bool = False,
    ) -> WorkspaceMembership | None:
        statement = select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_for_workspace(
        self,
        *,
        workspace_id: uuid.UUID,
    ) -> list[WorkspaceMembership]:
        rows = await self.session.scalars(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(WorkspaceMembership.created_at, WorkspaceMembership.id)
        )
        return list(rows)
