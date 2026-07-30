"""Execution-context-bound persistence for H2-02 credential custody."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.connection_credentials.contracts import InventorySummary
from app.connection_credentials.models import (
    ConnectionCredential,
    CredentialMigrationInventory,
)
from app.execution_context import ContextBoundRepository, ExecutionContext


class ConnectionCredentialRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add_credential(
        self, credential: ConnectionCredential
    ) -> ConnectionCredential:
        self.require_workspace(credential.workspace_id)
        self.session.add(credential)
        await self.session.flush()
        return credential

    async def get_credential(
        self,
        credential_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> ConnectionCredential | None:
        statement = select(ConnectionCredential).where(
            ConnectionCredential.workspace_id == self.context.tenant.workspace_id,
            ConnectionCredential.id == credential_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def latest_generation(
        self,
        connection_id: uuid.UUID,
        credential_kind: str,
        *,
        for_update: bool = False,
    ) -> ConnectionCredential | None:
        statement = (
            select(ConnectionCredential)
            .where(
                ConnectionCredential.workspace_id
                == self.context.tenant.workspace_id,
                ConnectionCredential.connection_id == connection_id,
                ConnectionCredential.credential_kind == credential_kind,
            )
            .order_by(ConnectionCredential.generation.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def inventory_item(
        self,
        source_system: str,
        source_record_id: str,
        *,
        for_update: bool = False,
    ) -> CredentialMigrationInventory | None:
        statement = select(CredentialMigrationInventory).where(
            CredentialMigrationInventory.workspace_id
            == self.context.tenant.workspace_id,
            CredentialMigrationInventory.source_system == source_system,
            CredentialMigrationInventory.source_record_id == source_record_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def lock_inventory_source(
        self,
        source_system: str,
        source_record_id: str,
    ) -> None:
        """Serialize the same migration source for concurrent replay safety."""
        lock_key = (
            f"{self.context.tenant.workspace_id}|{source_system}|{source_record_id}"
        )
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": lock_key},
        )

    async def add_inventory(
        self, item: CredentialMigrationInventory
    ) -> CredentialMigrationInventory:
        self.require_workspace(item.workspace_id)
        self.session.add(item)
        await self.session.flush()
        return item

    async def summary(self) -> InventorySummary:
        workspace_id = self.context.tenant.workspace_id
        rows = list(
            await self.session.scalars(
                select(CredentialMigrationInventory)
                .where(CredentialMigrationInventory.workspace_id == workspace_id)
                .order_by(
                    CredentialMigrationInventory.source_system,
                    CredentialMigrationInventory.source_record_id,
                )
            )
        )
        import hashlib

        digest = hashlib.sha256()
        all_scopes: set[str] = set()
        for row in rows:
            digest.update(
                f"{row.source_system}|{row.source_record_id}|"
                f"{row.source_checksum}|{row.status}\n".encode()
            )
            all_scopes.update(row.scopes)
        return InventorySummary(
            row_count=len(rows),
            eligible_count=sum(
                row.status in {"eligible", "migrated", "verified"} for row in rows
            ),
            verified_count=sum(row.status == "verified" for row in rows),
            exception_count=sum(
                row.status in {"reauthorization_required", "failed"} for row in rows
            ),
            inventory_checksum=digest.hexdigest(),
            scope_inventory=tuple(sorted(all_scopes)),
        )
