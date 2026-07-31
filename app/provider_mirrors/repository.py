"""Execution-context-bound H2-04 provider mirror persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.provider_mirrors.models import (
    ProviderExternalReference,
    ProviderMirror,
    ProviderMirrorComparison,
    ProviderMirrorConflict,
)


class ProviderMirrorRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def lock_idempotency(self, key: str) -> None:
        value = f"{self.context.tenant.workspace_id}|mirror|{key}"
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": value},
        )

    async def add_mirror(self, mirror: ProviderMirror) -> ProviderMirror:
        self.require_workspace(mirror.workspace_id)
        self.session.add(mirror)
        await self.session.flush()
        return mirror

    async def add_reference(
        self, reference: ProviderExternalReference
    ) -> ProviderExternalReference:
        self.require_workspace(reference.workspace_id)
        self.session.add(reference)
        await self.session.flush()
        return reference

    async def add_comparison(
        self, comparison: ProviderMirrorComparison
    ) -> ProviderMirrorComparison:
        self.require_workspace(comparison.workspace_id)
        self.session.add(comparison)
        await self.session.flush()
        return comparison

    async def add_conflict(
        self, conflict: ProviderMirrorConflict
    ) -> ProviderMirrorConflict:
        self.require_workspace(conflict.workspace_id)
        self.session.add(conflict)
        await self.session.flush()
        return conflict

    async def mirror(
        self, mirror_id: uuid.UUID, *, for_update: bool = False
    ) -> ProviderMirror | None:
        statement = select(ProviderMirror).where(
            ProviderMirror.workspace_id == self.context.tenant.workspace_id,
            ProviderMirror.id == mirror_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def reference(
        self, mirror_id: uuid.UUID, *, for_update: bool = False
    ) -> ProviderExternalReference | None:
        statement = select(ProviderExternalReference).where(
            ProviderExternalReference.workspace_id
            == self.context.tenant.workspace_id,
            ProviderExternalReference.mirror_id == mirror_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def comparison(
        self, idempotency_key: str
    ) -> ProviderMirrorComparison | None:
        return await self.session.scalar(
            select(ProviderMirrorComparison).where(
                ProviderMirrorComparison.workspace_id
                == self.context.tenant.workspace_id,
                ProviderMirrorComparison.idempotency_key == idempotency_key,
            )
        )

    async def conflict(
        self, conflict_id: uuid.UUID, *, for_update: bool = False
    ) -> ProviderMirrorConflict | None:
        statement = select(ProviderMirrorConflict).where(
            ProviderMirrorConflict.workspace_id
            == self.context.tenant.workspace_id,
            ProviderMirrorConflict.id == conflict_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def open_conflict(
        self, mirror_id: uuid.UUID
    ) -> ProviderMirrorConflict | None:
        return await self.session.scalar(
            select(ProviderMirrorConflict).where(
                ProviderMirrorConflict.workspace_id
                == self.context.tenant.workspace_id,
                ProviderMirrorConflict.mirror_id == mirror_id,
                ProviderMirrorConflict.status == "open",
            )
        )
