"""Provider-neutral reversible email routing."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.capability_routing.contracts import AuthorizationGate, MutationGuard
from app.email_capability.contracts import (
    CanonicalEmailPortFactory,
    EmailOperation,
    EmailRoute,
    EmailRoutingStore,
)
from app.email_capability.repository import EmailRoutingRepository
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.provider_capabilities.common import MutationContext, Page, to_wire
from app.provider_capabilities.email import (
    EmailListRequest,
    EmailMessage,
    EmailMessageCreate,
    EmailPort,
    EmailProfile,
    EmailSearchRequest,
)
from app.tenancy.models import OutboxEvent

T = TypeVar("T")


class EmailCapabilityService:
    def __init__(
        self,
        legacy: EmailPort,
        canonical_factory: CanonicalEmailPortFactory,
        routing: EmailRoutingStore,
        authorization: AuthorizationGate,
        mutation_guard: MutationGuard | None = None,
    ) -> None:
        self._legacy = legacy
        self._factory = canonical_factory
        self._routing = routing
        self._authorization = authorization
        self._mutations = mutation_guard

    async def profile(self) -> EmailProfile:
        return await self._read(EmailOperation.PROFILE, lambda port: port.profile())

    async def list_messages(
        self, request: EmailListRequest
    ) -> Page[EmailMessage]:
        return await self._read(
            EmailOperation.LIST, lambda port: port.list_messages(request)
        )

    async def list_unread(self, request: EmailListRequest) -> Page[EmailMessage]:
        return await self._read(
            EmailOperation.UNREAD, lambda port: port.list_unread(request)
        )

    async def search_messages(
        self, request: EmailSearchRequest
    ) -> Page[EmailMessage]:
        return await self._read(
            EmailOperation.SEARCH, lambda port: port.search_messages(request)
        )

    async def create_draft(
        self, message: EmailMessageCreate, context: MutationContext
    ) -> EmailMessage:
        await self._authorization.require("update_content")
        route = await self._routing.route()
        port = (
            await self._factory.canonical_port()
            if route is EmailRoute.CANONICAL
            else self._legacy
        )
        return await port.create_draft(message, context)

    async def send_message(
        self,
        message: EmailMessageCreate,
        context: MutationContext,
        *,
        approval_id: str,
    ) -> EmailMessage:
        await self._authorization.require("update_content")
        if self._mutations is None:
            raise RuntimeError("A mutation guard is required for sending email.")
        await self._mutations.require_approval(approval_id)
        route = await self._routing.route()
        port = (
            await self._factory.canonical_port()
            if route is EmailRoute.CANONICAL
            else self._legacy
        )
        digest = hashlib.sha256(
            json.dumps(to_wire(message), sort_keys=True).encode()
        ).hexdigest()
        return await self._mutations.execute_once(
            context.idempotency_key,
            digest,
            lambda: port.send_message(message, context),
        )

    async def _read(
        self, operation: EmailOperation, call: Callable[[EmailPort], Awaitable[T]]
    ) -> T:
        await self._authorization.require("read_content")
        route = await self._routing.route()
        if route is EmailRoute.LEGACY:
            return await call(self._legacy)
        canonical = await self._factory.canonical_port()
        if route is EmailRoute.CANONICAL:
            return await call(canonical)
        legacy_value = await call(self._legacy)
        canonical_value = await call(canonical)
        await self._routing.record_comparison(
            operation, to_wire(legacy_value) == to_wire(canonical_value)
        )
        return legacy_value


class EmailRouteControlService:
    """Authorized and audited reversible route changes."""

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
        self._repository = EmailRoutingRepository(
            session, context, connection_id=connection_id
        )
        self._audit = AuditWriterService(session, context)

    async def set_route(self, route: EmailRoute) -> None:
        await self._authorization.require("manage_workspace")
        if await self._repository.route() is route:
            return
        row = await self._repository.set_route(route)
        await self._audit.write(
            AuditInput(
                action="email.route_changed",
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
                event_type="email.route.changed",
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="email_route",
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
