"""Execution-context-bound repository for H3-08 workflows."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.workflows.models import (
    WorkflowDefinitionRecord,
    WorkflowDefinitionVersion,
    WorkflowInstance,
)


class WorkflowRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, value: object) -> object:
        self.require_workspace(getattr(value, "workspace_id"))
        self.session.add(value)
        await self.session.flush()
        return value

    async def definition(self, definition_id: uuid.UUID) -> WorkflowDefinitionRecord | None:
        return await self.session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.workspace_id == self.context.tenant.workspace_id,
                WorkflowDefinitionRecord.id == definition_id,
            )
        )

    async def definition_version(
        self, definition_id: uuid.UUID, version: int
    ) -> WorkflowDefinitionVersion | None:
        return await self.session.scalar(
            select(WorkflowDefinitionVersion).where(
                WorkflowDefinitionVersion.workspace_id == self.context.tenant.workspace_id,
                WorkflowDefinitionVersion.definition_id == definition_id,
                WorkflowDefinitionVersion.version == version,
            )
        )

    async def instance(
        self, instance_id: uuid.UUID, *, for_update: bool = False
    ) -> WorkflowInstance | None:
        statement = select(WorkflowInstance).where(
            WorkflowInstance.workspace_id == self.context.tenant.workspace_id,
            WorkflowInstance.id == instance_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)
