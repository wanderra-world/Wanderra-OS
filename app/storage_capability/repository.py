from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.storage_capability.contracts import StorageOperation, StorageRoute
from app.storage_capability.models import StorageCapabilityRoute, StorageShadowComparison


class StorageRoutingRepository(ContextBoundRepository):
    def __init__(
        self, session: AsyncSession, context: ExecutionContext, *, connection_id: uuid.UUID
    ):
        super().__init__(session, context)
        self._connection_id = connection_id

    async def route(self) -> StorageRoute:
        workspace = self.context.tenant.workspace_id
        self.require_workspace(workspace)
        value = await self.session.scalar(
            select(StorageCapabilityRoute.route).where(
                StorageCapabilityRoute.workspace_id == workspace,
                StorageCapabilityRoute.connection_id == self._connection_id,
            )
        )
        return StorageRoute(value or StorageRoute.LEGACY)

    async def set_route(self, route: StorageRoute) -> StorageCapabilityRoute:
        workspace = self.context.tenant.workspace_id
        self.require_workspace(workspace)
        row = await self.session.get(
            StorageCapabilityRoute, (workspace, self._connection_id), with_for_update=True
        )
        if row is None:
            row = StorageCapabilityRoute(
                workspace_id=workspace,
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

    async def record_comparison(self, operation: StorageOperation, equivalent: bool) -> None:
        workspace = self.context.tenant.workspace_id
        self.require_workspace(workspace)
        self.session.add(
            StorageShadowComparison(
                workspace_id=workspace,
                connection_id=self._connection_id,
                correlation_id=self.context.request.correlation_id,
                operation=operation.value,
                equivalent=equivalent,
            )
        )
        await self.session.flush()
