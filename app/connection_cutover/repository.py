"""Execution-context-bound H2-09 evidence and routing repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar_capability.models import CalendarCapabilityRoute, CalendarShadowComparison
from app.capability_routing.contracts import CapabilityRoute
from app.connection_cutover.contracts import IntegrationCapability, ShadowMetrics
from app.connection_cutover.models import CapabilityCutoverEvidence, ConnectionBackfillEvidence
from app.email_capability.models import EmailCapabilityRoute, EmailShadowComparison
from app.execution_context import ContextBoundRepository, ExecutionContext
from app.storage_capability.models import StorageCapabilityRoute, StorageShadowComparison

ROUTE_MODELS = {
    IntegrationCapability.EMAIL: EmailCapabilityRoute,
    IntegrationCapability.CALENDAR: CalendarCapabilityRoute,
    IntegrationCapability.STORAGE: StorageCapabilityRoute,
}
COMPARISON_MODELS = {
    IntegrationCapability.EMAIL: EmailShadowComparison,
    IntegrationCapability.CALENDAR: CalendarShadowComparison,
    IntegrationCapability.STORAGE: StorageShadowComparison,
}


class CutoverRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def metrics(
        self, connection_id: uuid.UUID, capability: IntegrationCapability
    ) -> ShadowMetrics:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        model = COMPARISON_MODELS[capability]
        row = (
            await self.session.execute(
                select(func.count(), func.count().filter(model.equivalent)).where(
                    model.workspace_id == workspace_id,
                    model.connection_id == connection_id,
                )
            )
        ).one()
        return ShadowMetrics(samples=int(row[0]), matches=int(row[1]))

    async def routes(
        self, connection_id: uuid.UUID, capability: IntegrationCapability
    ) -> tuple[CapabilityRoute, CapabilityRoute]:
        workspace_id = self.context.tenant.workspace_id
        model = ROUTE_MODELS[capability]
        row = await self.session.get(model, (workspace_id, connection_id), with_for_update=True)
        if row is None:
            return CapabilityRoute.LEGACY, CapabilityRoute.LEGACY
        return CapabilityRoute(row.route), CapabilityRoute(row.mutation_route)

    async def set_route(
        self,
        connection_id: uuid.UUID,
        capability: IntegrationCapability,
        *,
        route_kind: str,
        route: CapabilityRoute,
    ) -> None:
        workspace_id = self.context.tenant.workspace_id
        model = ROUTE_MODELS[capability]
        row = await self.session.get(model, (workspace_id, connection_id), with_for_update=True)
        if row is None:
            row = model(
                workspace_id=workspace_id,
                connection_id=connection_id,
                route="legacy",
                mutation_route="legacy",
                updated_by_user_id=self.context.actor.actor_id,
            )
            self.session.add(row)
        attribute = "route" if route_kind == "read" else "mutation_route"
        if getattr(row, attribute) != route.value:
            setattr(row, attribute, route.value)
            row.version += 1
            row.updated_by_user_id = self.context.actor.actor_id
        await self.session.flush()

    async def add_cutover_evidence(self, evidence: CapabilityCutoverEvidence) -> None:
        self.require_workspace(evidence.workspace_id)
        self.session.add(evidence)
        await self.session.flush()

    async def add_backfill_evidence(self, evidence: ConnectionBackfillEvidence) -> None:
        self.require_workspace(evidence.workspace_id)
        existing = await self.session.get(
            ConnectionBackfillEvidence,
            (evidence.workspace_id, evidence.source_system, evidence.source_record_id),
            with_for_update=True,
        )
        if existing is None:
            self.session.add(evidence)
        elif (
            existing.connection_id != evidence.connection_id
            or existing.source_checksum != evidence.source_checksum
            or existing.evidence_checksum != evidence.evidence_checksum
        ):
            raise ValueError("backfill replay does not match recorded evidence")
        else:
            existing.attempt_count += 1
        await self.session.flush()
