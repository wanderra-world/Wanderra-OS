"""Repository boundary that rejects missing or mismatched tenant context."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context.contracts import ExecutionContext


class ExecutionContextRequiredError(RuntimeError):
    """Raised before tenant repository access without valid bound context."""


class ContextBoundRepository:
    """Base contract for new H1 tenant-owned repositories."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
    ) -> None:
        self.session = session
        self.context = context

    def require_workspace(self, workspace_id: uuid.UUID) -> None:
        bound = self.session.info.get("atlas.execution_context")
        if bound is None:
            raise ExecutionContextRequiredError(
                "transaction execution context is required"
            )
        if bound != self.context:
            raise ExecutionContextRequiredError(
                "repository and transaction contexts do not match"
            )
        if workspace_id != self.context.tenant.workspace_id:
            raise ExecutionContextRequiredError(
                "cross-workspace repository access is prohibited"
            )
