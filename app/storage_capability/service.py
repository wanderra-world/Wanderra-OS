from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.capability_routing.contracts import AuthorizationGate, MutationGuard
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.provider_capabilities.common import to_wire
from app.storage_capability.contracts import StorageOperation, StorageRoute
from app.storage_capability.repository import StorageRoutingRepository
from app.tenancy.models import OutboxEvent


class StorageCapabilityService:
    def __init__(
        self, legacy, factory, routing, authorization: AuthorizationGate, mutations: MutationGuard
    ):
        self._legacy = legacy
        self._factory = factory
        self._routing = routing
        self._authorization = authorization
        self._mutations = mutations

    async def _read(self, operation, call):
        await self._authorization.require("read_content")
        route = await self._routing.route()
        if route is StorageRoute.LEGACY:
            return await call(self._legacy)
        canonical = await self._factory.canonical_port()
        if route is StorageRoute.CANONICAL:
            return await call(canonical)
        legacy = await call(self._legacy)
        current = await call(canonical)
        await self._routing.record_comparison(operation, to_wire(legacy) == to_wire(current))
        return legacy

    async def list_objects(self, r):
        return await self._read(StorageOperation.LIST, lambda p: p.list_objects(r))

    async def search_objects(self, r):
        return await self._read(StorageOperation.SEARCH, lambda p: p.search_objects(r))

    async def read_metadata(self, i):
        return await self._read(StorageOperation.METADATA, lambda p: p.read_metadata(i))

    async def download(self, i):
        return await self._read(StorageOperation.DOWNLOAD, lambda p: p.download(i))

    async def read_text(self, i):
        return await self._read(StorageOperation.READ_TEXT, lambda p: p.read_text(i))

    async def _mutate(self, operation, context, approval, value, call, precondition):
        await self._authorization.require("update_content")
        if precondition and context.precondition is None:
            raise ValueError("A version precondition is required.")
        await self._mutations.require_approval(approval)
        route = await self._routing.route()
        port = (
            await self._factory.canonical_port()
            if route is StorageRoute.CANONICAL
            else self._legacy
        )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "operation": operation.value,
                    "value": to_wire(value),
                    "precondition": to_wire(context.precondition),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return await self._mutations.execute_once(
            context.idempotency_key, digest, lambda: call(port)
        )

    async def upload(self, item, context, *, approval_id):
        return await self._mutate(
            StorageOperation.UPLOAD,
            context,
            approval_id,
            {
                "name": item.name,
                "content_digest": hashlib.sha256(item.content).hexdigest(),
                "media_type": item.media_type,
                "parent_external_id": item.parent_external_id,
                "description": item.description,
            },
            lambda p: p.upload(item, context),
            False,
        )

    async def update_metadata(self, i, c, context, *, approval_id):
        return await self._mutate(
            StorageOperation.UPDATE_METADATA,
            context,
            approval_id,
            {"id": i, "changes": c},
            lambda p: p.update_metadata(i, c, context),
            True,
        )

    async def update_content(self, i, c, m, context, *, approval_id):
        return await self._mutate(
            StorageOperation.UPDATE_CONTENT,
            context,
            approval_id,
            {"id": i, "content_digest": hashlib.sha256(c).hexdigest(), "media_type": m},
            lambda p: p.update_content(i, c, m, context),
            True,
        )

    async def delete(self, i, context, *, approval_id):
        return await self._mutate(
            StorageOperation.DELETE,
            context,
            approval_id,
            {"id": i},
            lambda p: p.delete(i, context),
            True,
        )


class StorageRouteControlService:
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
        self._repository = StorageRoutingRepository(session, context, connection_id=connection_id)
        self._audit = AuditWriterService(session, context)

    async def set_route(self, route: StorageRoute) -> None:
        await self._authorization.require("manage_workspace")
        if await self._repository.route() is route:
            return
        row = await self._repository.set_route(route)
        await self._audit.write(
            AuditInput(
                action="storage.route_changed",
                target_type="connection",
                target_id=self._connection_id,
                outcome="success",
                details={"route": route.value, "version": row.version},
            )
        )
        payload = {
            "connection_id": str(self._connection_id),
            "route": route.value,
            "version": row.version,
        }
        self._session.add(
            OutboxEvent(
                workspace_id=self._context.tenant.workspace_id,
                event_type="storage.route.changed",
                aggregate_type="storage_route",
                aggregate_id=self._connection_id,
                aggregate_sequence=row.version,
                actor_id=self._context.actor.actor_id,
                correlation_id=self._context.request.correlation_id,
                payload=payload,
                payload_digest=hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
            )
        )
        await self._session.flush()
