"""Execution-context-bound H2-03 OAuth transaction persistence."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.oauth_transactions.models import OAuthTransaction


class OAuthTransactionRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def lock_idempotency(self, key: str) -> None:
        value = f"{self.context.tenant.workspace_id}|oauth|{key}"
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": value},
        )

    async def add(self, transaction: OAuthTransaction) -> OAuthTransaction:
        self.require_workspace(transaction.workspace_id)
        self.session.add(transaction)
        await self.session.flush()
        return transaction

    async def by_idempotency(self, key: str) -> OAuthTransaction | None:
        return await self.session.scalar(
            select(OAuthTransaction).where(
                OAuthTransaction.workspace_id == self.context.tenant.workspace_id,
                OAuthTransaction.idempotency_key == key,
            )
        )

    async def by_id(
        self, transaction_id, *, for_update: bool = False
    ) -> OAuthTransaction | None:
        statement = select(OAuthTransaction).where(
            OAuthTransaction.workspace_id == self.context.tenant.workspace_id,
            OAuthTransaction.id == transaction_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def by_state(
        self, digest: str, *, for_update: bool = False
    ) -> OAuthTransaction | None:
        statement = select(OAuthTransaction).where(
            OAuthTransaction.workspace_id == self.context.tenant.workspace_id,
            OAuthTransaction.state_digest == digest,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)
