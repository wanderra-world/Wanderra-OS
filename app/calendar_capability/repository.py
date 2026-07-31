"""Execution-context-bound Calendar routing persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar_capability.contracts import CalendarOperation, CalendarRoute
from app.calendar_capability.models import (
    CalendarCapabilityRoute,
    CalendarShadowComparison,
)
from app.execution_context import ContextBoundRepository, ExecutionContext


class CalendarRoutingRepository(ContextBoundRepository):
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        connection_id: uuid.UUID,
    ) -> None:
        super().__init__(session, context)
        self._connection_id = connection_id

    async def route(self) -> CalendarRoute:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        value = await self.session.scalar(
            select(CalendarCapabilityRoute.route).where(
                CalendarCapabilityRoute.workspace_id == workspace_id,
                CalendarCapabilityRoute.connection_id == self._connection_id,
            )
        )
        return CalendarRoute(value or CalendarRoute.LEGACY)

    async def set_route(
        self, route: CalendarRoute
    ) -> CalendarCapabilityRoute:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        row = await self.session.get(
            CalendarCapabilityRoute,
            (workspace_id, self._connection_id),
            with_for_update=True,
        )
        if row is None:
            row = CalendarCapabilityRoute(
                workspace_id=workspace_id,
                connection_id=self._connection_id,
                route=route.value,
                updated_by_user_id=self.context.actor.actor_id,
            )
            self.session.add(row)
        elif row.route != route.value:
            row.route = route.value
            row.version += 1
            row.updated_by_user_id = self.context.actor.actor_id
        await self.session.flush()
        return row

    async def record_comparison(
        self, operation: CalendarOperation, equivalent: bool
    ) -> None:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        self.session.add(
            CalendarShadowComparison(
                workspace_id=workspace_id,
                connection_id=self._connection_id,
                correlation_id=self.context.request.correlation_id,
                operation=operation.value,
                equivalent=equivalent,
            )
        )
        await self.session.flush()
