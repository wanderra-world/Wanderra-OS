"""Execution-context-bound repository for H3-10 agent platform state."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_platform.models import (
    AgentEvaluationRun,
    AgentManifestRecord,
    AgentManifestVersion,
    AgentOrchestration,
    AgentPlan,
    AgentToolRecord,
    AgentToolVersion,
)
from app.execution_context import ContextBoundRepository, ExecutionContext


class AgentPlatformRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, value: object) -> object:
        self.require_workspace(getattr(value, "workspace_id"))
        self.session.add(value)
        await self.session.flush()
        return value

    async def manifest(self, manifest_id: uuid.UUID) -> AgentManifestRecord | None:
        return await self.session.scalar(
            select(AgentManifestRecord).where(
                AgentManifestRecord.workspace_id == self.context.tenant.workspace_id,
                AgentManifestRecord.id == manifest_id,
            )
        )

    async def manifest_version(
        self, manifest_id: uuid.UUID, version: int
    ) -> AgentManifestVersion | None:
        return await self.session.scalar(
            select(AgentManifestVersion).where(
                AgentManifestVersion.workspace_id == self.context.tenant.workspace_id,
                AgentManifestVersion.manifest_id == manifest_id,
                AgentManifestVersion.version == version,
            )
        )

    async def tool(self, key: str) -> AgentToolRecord | None:
        return await self.session.scalar(
            select(AgentToolRecord).where(
                AgentToolRecord.workspace_id == self.context.tenant.workspace_id,
                AgentToolRecord.tool_key == key,
            )
        )

    async def tool_version(self, tool_id: uuid.UUID, version: int) -> AgentToolVersion | None:
        return await self.session.scalar(
            select(AgentToolVersion).where(
                AgentToolVersion.workspace_id == self.context.tenant.workspace_id,
                AgentToolVersion.tool_id == tool_id,
                AgentToolVersion.version == version,
            )
        )

    async def has_passing_evaluation(self, manifest_id: uuid.UUID, version: int) -> bool:
        value = await self.session.scalar(
            select(AgentEvaluationRun.id).where(
                AgentEvaluationRun.workspace_id == self.context.tenant.workspace_id,
                AgentEvaluationRun.manifest_id == manifest_id,
                AgentEvaluationRun.manifest_version == version,
                AgentEvaluationRun.passed.is_(True),
            )
        )
        return value is not None

    async def plan(
        self, plan_id: uuid.UUID, version: int, *, for_update: bool = False
    ) -> AgentPlan | None:
        statement = select(AgentPlan).where(
            AgentPlan.workspace_id == self.context.tenant.workspace_id,
            AgentPlan.id == plan_id,
            AgentPlan.version == version,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def orchestration(
        self, orchestration_id: uuid.UUID, *, for_update: bool = False
    ) -> AgentOrchestration | None:
        statement = select(AgentOrchestration).where(
            AgentOrchestration.workspace_id == self.context.tenant.workspace_id,
            AgentOrchestration.id == orchestration_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)
