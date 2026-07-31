"""Execution-context-bound email routing persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.email_capability.contracts import EmailOperation, EmailRoute
from app.email_capability.models import EmailCapabilityRoute, EmailShadowComparison
from app.execution_context import ContextBoundRepository, ExecutionContext


class EmailRoutingRepository(ContextBoundRepository):
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        connection_id: uuid.UUID,
    ) -> None:
        super().__init__(session, context)
        self._connection_id = connection_id

    async def route(self) -> EmailRoute:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        value = await self.session.scalar(
            select(EmailCapabilityRoute.route).where(
                EmailCapabilityRoute.workspace_id == workspace_id,
                EmailCapabilityRoute.connection_id == self._connection_id,
            )
        )
        return EmailRoute(value or EmailRoute.LEGACY)

    async def set_route(self, route: EmailRoute) -> EmailCapabilityRoute:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        row = await self.session.get(
            EmailCapabilityRoute,
            (workspace_id, self._connection_id),
            with_for_update=True,
        )
        if row is None:
            row = EmailCapabilityRoute(
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
        self, operation: EmailOperation, equivalent: bool
    ) -> None:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        self.session.add(
            EmailShadowComparison(
                workspace_id=workspace_id,
                connection_id=self._connection_id,
                correlation_id=self.context.request.correlation_id,
                operation=operation.value,
                equivalent=equivalent,
            )
        )
        await self.session.flush()
