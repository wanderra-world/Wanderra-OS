"""Deterministic backfill planning and fail-closed cutover decisions."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.capability_routing.contracts import AuthorizationGate, CapabilityRoute
from app.connection_cutover.contracts import (
    BackfillCandidate,
    BackfillPlan,
    CutoverDecision,
    CutoverThreshold,
    IntegrationCapability,
    ShadowMetrics,
)
from app.connection_cutover.models import CapabilityCutoverEvidence, ConnectionBackfillEvidence
from app.connection_cutover.repository import CutoverRepository
from app.connections.contracts import CapabilityGrant, ConnectionCreate, ConnectionStatus
from app.connections.models import Connection
from app.connections.service import ConnectionAuthorizer, ConnectionService
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent


class CutoverNotReadyError(RuntimeError):
    """Raised when evidence does not authorize canonical routing."""


class BackfillPlanner:
    """Produce stable connection identity and reconciliation evidence."""

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

    def plan(self, candidates: Iterable[BackfillCandidate]) -> BackfillPlan:
        records = tuple(
            sorted(candidates, key=lambda item: (item.capability.value, item.source_record_id))
        )
        if not records:
            raise ValueError("at least one legacy integration is required")
        first = records[0]
        boundary = {(item.workspace_id, item.provider_account_id) for item in records}
        if len(boundary) != 1:
            raise ValueError("backfill requires one workspace and provider account")
        if any(
            item.organization_id != first.organization_id
            or item.cell_id != first.cell_id
            or item.user_id != first.user_id
            for item in records
        ):
            raise ValueError("backfill candidates must share placement and identity")
        duplicate_capabilities = len({item.capability for item in records}) != len(records)
        if duplicate_capabilities:
            raise ValueError("one legacy record per capability is required")
        connection_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"atlas:{first.workspace_id}:google_workspace:{first.provider_account_id}",
        )
        payload = {
            "workspace_id": str(first.workspace_id),
            "connection_id": str(connection_id),
            "provider_account_id": first.provider_account_id,
            "records": [
                {
                    "capability": item.capability.value,
                    "source_record_id": item.source_record_id,
                    "source_checksum": item.source_checksum,
                    "eligible": item.credential_eligible,
                }
                for item in records
            ],
        }
        checksum = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return BackfillPlan(
            workspace_id=first.workspace_id,
            connection_id=connection_id,
            provider_account_id=first.provider_account_id,
            capabilities=tuple(item.capability for item in records),
            source_records=tuple(item.source_record_id for item in records),
            evidence_checksum=checksum,
            exception_code=(
                None
                if all(item.credential_eligible for item in records)
                else "reauthorization_required"
            ),
        )


class CutoverReadiness:
    """Evaluate an explicit failure budget before canonical cutover."""

    def __init__(self, threshold: CutoverThreshold) -> None:
        self._threshold = threshold

    def evaluate(self, metrics: ShadowMetrics) -> CutoverDecision:
        if metrics.samples < self._threshold.minimum_samples:
            return CutoverDecision(False, "insufficient_samples", metrics, self._threshold)
        if metrics.mismatch_rate > self._threshold.maximum_mismatch_rate:
            return CutoverDecision(False, "failure_budget_exceeded", metrics, self._threshold)
        return CutoverDecision(True, "threshold_satisfied", metrics, self._threshold)

    def require_transition(
        self,
        *,
        current: CapabilityRoute,
        requested: CapabilityRoute,
        metrics: ShadowMetrics,
        require_shadow: bool = True,
    ) -> CapabilityRoute:
        if requested is not CapabilityRoute.CANONICAL:
            return requested
        if require_shadow and current is CapabilityRoute.LEGACY:
            raise CutoverNotReadyError("canonical cutover requires shadow routing first")
        decision = self.evaluate(metrics)
        if not decision.ready:
            raise CutoverNotReadyError(decision.reason)
        return requested


class ConnectionCutoverService:
    """Authorize, evidence, and apply independently reversible route changes."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorization: AuthorizationGate,
        threshold: CutoverThreshold,
    ) -> None:
        self._session = session
        self._context = context
        self._authorization = authorization
        self._repository = CutoverRepository(session, context)
        self._readiness = CutoverReadiness(threshold)
        self._threshold = threshold
        self._audit = AuditWriterService(session, context)

    async def set_route(
        self,
        connection_id: uuid.UUID,
        capability: IntegrationCapability,
        *,
        route_kind: str,
        requested: CapabilityRoute,
    ) -> None:
        if route_kind not in {"read", "mutation"}:
            raise ValueError("route kind must be read or mutation")
        await self._authorization.require("manage_workspace")
        read_route, mutation_route = await self._repository.routes(connection_id, capability)
        current = read_route if route_kind == "read" else mutation_route
        metrics = await self._repository.metrics(connection_id, capability)
        try:
            accepted = self._readiness.require_transition(
                current=current,
                requested=requested,
                metrics=metrics,
                require_shadow=route_kind == "read",
            )
            approved = True
            reason = "rollback" if requested is CapabilityRoute.LEGACY else "threshold_satisfied"
        except CutoverNotReadyError as exc:
            accepted = requested
            approved = False
            reason = str(exc)
        evidence = CapabilityCutoverEvidence(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=connection_id,
            capability=capability.value,
            route_kind=route_kind,
            requested_route=requested.value,
            samples=metrics.samples,
            matches=metrics.matches,
            minimum_samples=self._threshold.minimum_samples,
            maximum_mismatch_rate=str(self._threshold.maximum_mismatch_rate),
            approved=approved,
            reason=reason,
            actor_id=self._context.actor.actor_id,
        )
        await self._repository.add_cutover_evidence(evidence)
        if not approved:
            await self._audit.write(
                AuditInput(
                    action="connection.cutover_denied",
                    target_type="connection",
                    target_id=connection_id,
                    outcome="failure",
                    details={
                        "capability": capability.value,
                        "route_kind": route_kind,
                        "reason": reason,
                    },
                )
            )
            raise CutoverNotReadyError(reason)
        await self._repository.set_route(
            connection_id, capability, route_kind=route_kind, route=accepted
        )
        await self._audit.write(
            AuditInput(
                action="connection.route_cutover",
                target_type="connection",
                target_id=connection_id,
                outcome="success",
                details={
                    "capability": capability.value,
                    "route_kind": route_kind,
                    "route": accepted.value,
                    "samples": metrics.samples,
                    "matches": metrics.matches,
                },
            )
        )
        payload: dict[str, object] = {
            "connection_id": str(connection_id),
            "capability": capability.value,
            "route_kind": route_kind,
            "route": accepted.value,
            "samples": metrics.samples,
            "matches": metrics.matches,
        }
        sequence = (
            await self._session.scalar(
                select(func.coalesce(func.max(OutboxEvent.aggregate_sequence), 0)).where(
                    OutboxEvent.workspace_id == self._context.tenant.workspace_id,
                    OutboxEvent.aggregate_type == "connection",
                    OutboxEvent.aggregate_id == connection_id,
                )
            )
        ) + 1
        self._session.add(
            OutboxEvent(
                workspace_id=self._context.tenant.workspace_id,
                event_type="connection.route.cutover",
                aggregate_type="connection",
                aggregate_id=connection_id,
                aggregate_sequence=sequence,
                actor_id=self._context.actor.actor_id,
                correlation_id=self._context.request.correlation_id,
                payload=payload,
                payload_digest=hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
            )
        )
        await self._session.flush()


_CAPABILITY_GRANTS = {
    IntegrationCapability.EMAIL: ("email.read", "email.send"),
    IntegrationCapability.CALENDAR: ("calendar.read", "calendar.write"),
    IntegrationCapability.STORAGE: ("storage.read", "storage.write"),
}
_SOURCE_SYSTEM = {
    IntegrationCapability.EMAIL: "gmail_credentials",
    IntegrationCapability.CALENDAR: "calendar_credentials",
    IntegrationCapability.STORAGE: "drive_credentials",
}


class ConnectionBackfillService:
    """Apply a deterministic, restartable legacy-integration connection backfill."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: ConnectionAuthorizer,
    ) -> None:
        self._session = session
        self._context = context
        self._connections = ConnectionService(session, context, authorizer=authorizer)
        self._repository = CutoverRepository(session, context)

    async def apply(self, candidates: Iterable[BackfillCandidate]) -> BackfillPlan:
        records = tuple(candidates)
        plan = BackfillPlanner().plan(records)
        workspace_id = self._context.tenant.workspace_id
        if plan.workspace_id != workspace_id:
            raise ValueError("backfill plan does not match execution workspace")
        connection = await self._session.scalar(
            select(Connection).where(
                Connection.workspace_id == workspace_id,
                Connection.id == plan.connection_id,
            )
        )
        if connection is None:
            grant_keys = sorted(
                {
                    grant
                    for capability in plan.capabilities
                    for grant in _CAPABILITY_GRANTS[capability]
                }
            )
            connection = await self._connections.create(
                ConnectionCreate(
                    connection_id=plan.connection_id,
                    provider_key="google_workspace",
                    connection_kind="workspace_suite",
                    provider_account_id=plan.provider_account_id,
                    display_name=plan.provider_account_id,
                    capability_grants=tuple(CapabilityGrant(key) for key in grant_keys),
                )
            )
            target = (
                ConnectionStatus.REAUTHORIZATION_REQUIRED
                if plan.exception_code
                else ConnectionStatus.ACTIVE
            )
            await self._connections.transition(
                connection_id=connection.id,
                expected_version=connection.version,
                target=target,
            )
        elif connection.provider_account_id != plan.provider_account_id:
            raise ValueError("deterministic connection identity collision")
        for record in records:
            await self._repository.add_backfill_evidence(
                ConnectionBackfillEvidence(
                    workspace_id=workspace_id,
                    source_system=_SOURCE_SYSTEM[record.capability],
                    source_record_id=record.source_record_id,
                    connection_id=plan.connection_id,
                    source_checksum=record.source_checksum,
                    evidence_checksum=plan.evidence_checksum,
                    status=("reauthorization_required" if plan.exception_code else "mapped"),
                )
            )
        return plan
