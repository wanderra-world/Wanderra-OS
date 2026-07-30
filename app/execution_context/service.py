"""Request-scoped binding and PostgreSQL propagation for execution context."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context.contracts import ExecutionContext

_current_context: ContextVar[ExecutionContext | None] = ContextVar(
    "atlas_execution_context",
    default=None,
)


class ExecutionContextError(RuntimeError):
    """Raised before repository access when execution context is invalid."""


def current_execution_context() -> ExecutionContext:
    """Return the request-scoped context or deny context-free execution."""
    context = _current_context.get()
    if context is None:
        raise ExecutionContextError("execution context is required")
    return context


class ExecutionContextService:
    """Validate, bind, and propagate one context into one database transaction."""

    @contextmanager
    def bind(self, context: ExecutionContext) -> Iterator[ExecutionContext]:
        token: Token[ExecutionContext | None] = _current_context.set(context)
        try:
            yield context
        finally:
            _current_context.reset(token)

    async def apply(
        self,
        session: AsyncSession,
        context: ExecutionContext,
    ) -> None:
        """Validate placement and set transaction-local PostgreSQL context."""
        if not session.in_transaction():
            raise ExecutionContextError("an active transaction is required")

        placement = (
            await session.execute(
                text(
                    """
                    SELECT w.organization_id, w.cell_id, w.status, c.status AS cell_status
                    FROM workspaces AS w
                    JOIN cells AS c ON c.id = w.cell_id
                    WHERE w.workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": context.tenant.workspace_id},
            )
        ).mappings().one_or_none()
        if placement is None:
            raise ExecutionContextError("workspace context is stale or unknown")
        if (
            placement["organization_id"] != context.tenant.organization_id
            or placement["cell_id"] != context.tenant.cell_id
        ):
            raise ExecutionContextError("tenant placement context does not match")
        if placement["status"] == "closed" or placement["cell_status"] != "active":
            raise ExecutionContextError("tenant placement is not active")

        settings = {
            "atlas.workspace_id": str(context.tenant.workspace_id),
            "atlas.organization_id": str(context.tenant.organization_id),
            "atlas.cell_id": str(context.tenant.cell_id),
            "atlas.actor_id": str(context.actor.actor_id),
            "atlas.session_id": str(context.actor.session_id),
            "atlas.membership_id": str(context.actor.membership_id),
            "atlas.authorization_decision_id": str(
                context.actor.authorization_decision_id
            ),
            "atlas.request_id": context.request.request_id,
            "atlas.correlation_id": context.request.correlation_id,
        }
        if context.actor.delegation_id is not None:
            settings["atlas.delegation_id"] = str(context.actor.delegation_id)

        for key, value in settings.items():
            await session.execute(
                text("SELECT set_config(:key, :value, TRUE)"),
                {"key": key, "value": value},
            )
        session.info["atlas.execution_context"] = context

    @asynccontextmanager
    async def transaction(
        self,
        session: AsyncSession,
        context: ExecutionContext,
    ) -> AsyncIterator[ExecutionContext]:
        """Bind context for exactly one transaction and clear application state."""
        with self.bind(context):
            async with session.begin():
                await self.apply(session, context)
                try:
                    yield context
                finally:
                    session.info.pop("atlas.execution_context", None)
