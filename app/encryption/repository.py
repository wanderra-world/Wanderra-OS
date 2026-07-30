"""Context-bound repository for encrypted credential envelopes."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.encryption.models import EncryptedEnvelope
from app.execution_context import ContextBoundRepository, ExecutionContext


class EncryptionRepository(ContextBoundRepository):
    """Persist envelopes with mandatory workspace execution context."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
    ) -> None:
        super().__init__(session, context)

    async def add(self, envelope: EncryptedEnvelope) -> EncryptedEnvelope:
        self.require_workspace(envelope.workspace_id)
        self.session.add(envelope)
        await self.session.flush()
        return envelope

    async def get(
        self,
        *,
        workspace_id: uuid.UUID,
        envelope_id: uuid.UUID,
        for_update: bool = False,
    ) -> EncryptedEnvelope | None:
        self.require_workspace(workspace_id)
        statement = select(EncryptedEnvelope).where(
            EncryptedEnvelope.workspace_id == workspace_id,
            EncryptedEnvelope.id == envelope_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_by_record(
        self,
        *,
        workspace_id: uuid.UUID,
        record_type: str,
        record_id: uuid.UUID,
        for_update: bool = False,
    ) -> EncryptedEnvelope | None:
        self.require_workspace(workspace_id)
        statement = select(EncryptedEnvelope).where(
            EncryptedEnvelope.workspace_id == workspace_id,
            EncryptedEnvelope.record_type == record_type,
            EncryptedEnvelope.record_id == record_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)
