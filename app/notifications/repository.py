"""Execution-context-bound repository for H3-09 notifications."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.notifications.models import NotificationIntentRecord, NotificationPreferenceRecord


class NotificationRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, value: object) -> object:
        self.require_workspace(getattr(value, "workspace_id"))
        self.session.add(value)
        await self.session.flush()
        return value

    async def intent_by_deduplication_key(self, key: str) -> NotificationIntentRecord | None:
        return await self.session.scalar(
            select(NotificationIntentRecord).where(
                NotificationIntentRecord.workspace_id == self.context.tenant.workspace_id,
                NotificationIntentRecord.deduplication_key == key,
            )
        )

    async def preference(
        self, user_id: uuid.UUID, channel: str
    ) -> NotificationPreferenceRecord | None:
        return await self.session.scalar(
            select(NotificationPreferenceRecord).where(
                NotificationPreferenceRecord.workspace_id == self.context.tenant.workspace_id,
                NotificationPreferenceRecord.user_id == user_id,
                NotificationPreferenceRecord.channel == channel,
            )
        )
