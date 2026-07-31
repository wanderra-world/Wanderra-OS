"""Execution-context-bound Calendar routing persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
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

    async def mutation_route(self) -> CalendarRoute:
        workspace_id = self.context.tenant.workspace_id
        value = await self.session.scalar(
            select(CalendarCapabilityRoute.mutation_route).where(
                CalendarCapabilityRoute.workspace_id == workspace_id,
                CalendarCapabilityRoute.connection_id == self._connection_id,
            )
        )
        return CalendarRoute(value or CalendarRoute.LEGACY)

    async def set_route(self, route: CalendarRoute) -> CalendarCapabilityRoute:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        if not await self._supports_mutation_route():
            result = (
                (
                    await self.session.execute(
                        text(
                            """
                        INSERT INTO calendar_capability_routes (
                            workspace_id, connection_id, route, updated_by_user_id
                        ) VALUES (:workspace_id, :connection_id, :route, :actor_id)
                        ON CONFLICT (workspace_id, connection_id) DO UPDATE SET
                            route = EXCLUDED.route,
                            version = calendar_capability_routes.version + 1,
                            updated_by_user_id = EXCLUDED.updated_by_user_id
                        WHERE calendar_capability_routes.route <> EXCLUDED.route
                        RETURNING route, version
                        """
                        ),
                        {
                            "workspace_id": workspace_id,
                            "connection_id": self._connection_id,
                            "route": route.value,
                            "actor_id": self.context.actor.actor_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if result is None:
                result = (
                    (
                        await self.session.execute(
                            text(
                                """SELECT route, version FROM calendar_capability_routes
                            WHERE workspace_id=:workspace_id AND connection_id=:connection_id"""
                            ),
                            {"workspace_id": workspace_id, "connection_id": self._connection_id},
                        )
                    )
                    .mappings()
                    .one()
                )
            return CalendarCapabilityRoute(
                workspace_id=workspace_id,
                connection_id=self._connection_id,
                route=result["route"],
                mutation_route="legacy",
                version=result["version"],
                updated_by_user_id=self.context.actor.actor_id,
            )
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

    async def _supports_mutation_route(self) -> bool:
        return bool(
            await self.session.scalar(
                text(
                    """SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='calendar_capability_routes'
                      AND column_name='mutation_route')"""
                )
            )
        )

    async def record_comparison(self, operation: CalendarOperation, equivalent: bool) -> None:
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
