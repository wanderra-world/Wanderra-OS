"""Provider-neutral reversible Calendar routing."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar_capability.contracts import (
    CalendarOperation,
    CalendarRoute,
    CalendarRoutingStore,
    CanonicalCalendarPortFactory,
)
from app.calendar_capability.repository import CalendarRoutingRepository
from app.capability_routing.contracts import AuthorizationGate, MutationGuard
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.provider_capabilities.calendar import (
    CalendarEvent,
    CalendarEventCreate,
    CalendarEventPatch,
    CalendarListRequest,
    CalendarPort,
)
from app.provider_capabilities.common import MutationContext, Page, to_wire
from app.tenancy.models import OutboxEvent

T = TypeVar("T")


class CalendarCapabilityService:
    def __init__(
        self,
        legacy: CalendarPort,
        canonical_factory: CanonicalCalendarPortFactory,
        routing: CalendarRoutingStore,
        authorization: AuthorizationGate,
        mutation_guard: MutationGuard,
    ) -> None:
        self._legacy = legacy
        self._factory = canonical_factory
        self._routing = routing
        self._authorization = authorization
        self._mutations = mutation_guard

    async def list_events(
        self, request: CalendarListRequest
    ) -> Page[CalendarEvent]:
        await self._authorization.require("read_content")
        route = await self._routing.route()
        if route is CalendarRoute.LEGACY:
            return await self._legacy.list_events(request)
        canonical = await self._factory.canonical_port()
        if route is CalendarRoute.CANONICAL:
            return await canonical.list_events(request)
        legacy_value = await self._legacy.list_events(request)
        canonical_value = await canonical.list_events(request)
        await self._routing.record_comparison(
            CalendarOperation.LIST,
            to_wire(legacy_value) == to_wire(canonical_value),
        )
        return legacy_value

    async def create_event(
        self,
        event: CalendarEventCreate,
        context: MutationContext,
        *,
        approval_id: str,
    ) -> CalendarEvent:
        return await self._mutation(
            CalendarOperation.CREATE,
            context,
            approval_id,
            event,
            lambda port: port.create_event(event, context),
            require_precondition=False,
        )

    async def update_event(
        self,
        external_id: str,
        changes: CalendarEventPatch,
        context: MutationContext,
        *,
        approval_id: str,
    ) -> CalendarEvent:
        return await self._mutation(
            CalendarOperation.UPDATE,
            context,
            approval_id,
            {"external_id": external_id, "changes": changes},
            lambda port: port.update_event(external_id, changes, context),
            require_precondition=True,
        )

    async def delete_event(
        self,
        external_id: str,
        context: MutationContext,
        *,
        approval_id: str,
    ) -> None:
        return await self._mutation(
            CalendarOperation.DELETE,
            context,
            approval_id,
            {"external_id": external_id},
            lambda port: port.delete_event(external_id, context),
            require_precondition=True,
        )

    async def _mutation(
        self,
        operation: CalendarOperation,
        context: MutationContext,
        approval_id: str,
        value: object,
        call: Callable[[CalendarPort], Awaitable[T]],
        *,
        require_precondition: bool,
    ) -> T:
        await self._authorization.require("update_content")
        if require_precondition and context.precondition is None:
            raise ValueError("A version precondition is required.")
        await self._mutations.require_approval(approval_id)
        route = await self._routing.route()
        port = (
            await self._factory.canonical_port()
            if route is CalendarRoute.CANONICAL
            else self._legacy
        )
        request = {
            "operation": operation.value,
            "value": to_wire(value),
            "precondition": to_wire(context.precondition),
        }
        digest = hashlib.sha256(
            json.dumps(request, sort_keys=True).encode()
        ).hexdigest()
        return await self._mutations.execute_once(
            context.idempotency_key, digest, lambda: call(port)
        )


class CalendarRouteControlService:
    """Authorized and audited reversible Calendar route changes."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        connection_id: uuid.UUID,
        authorization: AuthorizationGate,
    ) -> None:
        self._session = session
        self._context = context
        self._connection_id = connection_id
        self._authorization = authorization
        self._repository = CalendarRoutingRepository(
            session, context, connection_id=connection_id
        )
        self._audit = AuditWriterService(session, context)

    async def set_route(self, route: CalendarRoute) -> None:
        await self._authorization.require("manage_workspace")
        if await self._repository.route() is route:
            return
        row = await self._repository.set_route(route)
        await self._audit.write(
            AuditInput(
                action="calendar.route_changed",
                target_type="connection",
                target_id=self._connection_id,
                outcome="success",
                details={"route": route.value, "version": row.version},
            )
        )
        payload: dict[str, object] = {
            "connection_id": str(self._connection_id),
            "route": route.value,
            "version": row.version,
        }
        self._session.add(
            OutboxEvent(
                workspace_id=self._context.tenant.workspace_id,
                event_type="calendar.route.changed",
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="calendar_route",
                aggregate_id=self._connection_id,
                aggregate_sequence=row.version,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="internal",
                payload=payload,
                payload_digest=hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
            )
        )
        await self._session.flush()
