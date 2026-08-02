"""Execution-context-bound persistence for H3-03 document custody."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import (
    Document,
    DocumentChunk,
    DocumentDeletion,
    DocumentDerivative,
    DocumentVersion,
)
from app.execution_context import ContextBoundRepository, ExecutionContext
from app.resource_graph.models import Resource


class DocumentRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, value: object) -> object:
        self.require_workspace(getattr(value, "workspace_id"))
        self.session.add(value)
        await self.session.flush()
        return value

    async def resource(self, resource_id: uuid.UUID) -> Resource | None:
        return await self.session.scalar(
            select(Resource).where(
                Resource.workspace_id == self.context.tenant.workspace_id,
                Resource.id == resource_id,
                Resource.status == "active",
            )
        )

    async def document(
        self, document_id: uuid.UUID, *, for_update: bool = False
    ) -> Document | None:
        statement = select(Document).where(
            Document.workspace_id == self.context.tenant.workspace_id,
            Document.id == document_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def version(
        self, version_id: uuid.UUID, *, for_update: bool = False
    ) -> DocumentVersion | None:
        statement = select(DocumentVersion).where(
            DocumentVersion.workspace_id == self.context.tenant.workspace_id,
            DocumentVersion.id == version_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def next_version_number(self, document_id: uuid.UUID) -> int:
        highest = await self.session.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.workspace_id == self.context.tenant.workspace_id,
                DocumentVersion.document_id == document_id,
            )
        )
        return int(highest or 0) + 1

    async def derivative_by_input(
        self, version_id: uuid.UUID, input_digest: str
    ) -> DocumentDerivative | None:
        return await self.session.scalar(
            select(DocumentDerivative).where(
                DocumentDerivative.workspace_id == self.context.tenant.workspace_id,
                DocumentDerivative.source_version_id == version_id,
                DocumentDerivative.input_digest == input_digest,
            )
        )

    async def versions(self, document_id: uuid.UUID) -> tuple[DocumentVersion, ...]:
        values = await self.session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.workspace_id == self.context.tenant.workspace_id,
                DocumentVersion.document_id == document_id,
            )
            .order_by(DocumentVersion.version_number)
            .with_for_update()
        )
        return tuple(values)

    async def derivatives(
        self, version_ids: tuple[uuid.UUID, ...]
    ) -> tuple[DocumentDerivative, ...]:
        if not version_ids:
            return ()
        values = await self.session.scalars(
            select(DocumentDerivative)
            .where(
                DocumentDerivative.workspace_id == self.context.tenant.workspace_id,
                DocumentDerivative.source_version_id.in_(version_ids),
            )
            .with_for_update()
        )
        return tuple(values)

    async def chunks(self, derivative_ids: tuple[uuid.UUID, ...]) -> tuple[DocumentChunk, ...]:
        if not derivative_ids:
            return ()
        values = await self.session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.workspace_id == self.context.tenant.workspace_id,
                DocumentChunk.derivative_id.in_(derivative_ids),
            )
            .with_for_update()
        )
        return tuple(values)

    async def deletion(
        self, deletion_id: uuid.UUID, *, for_update: bool = False
    ) -> DocumentDeletion | None:
        statement = select(DocumentDeletion).where(
            DocumentDeletion.workspace_id == self.context.tenant.workspace_id,
            DocumentDeletion.id == deletion_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def document_deletions(self, document_id: uuid.UUID) -> tuple[DocumentDeletion, ...]:
        values = await self.session.scalars(
            select(DocumentDeletion)
            .where(
                DocumentDeletion.workspace_id == self.context.tenant.workspace_id,
                DocumentDeletion.document_id == document_id,
            )
            .order_by(DocumentDeletion.requested_at, DocumentDeletion.id)
        )
        return tuple(values)
