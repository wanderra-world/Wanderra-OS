"""Workspace-owned H3-06 search projection persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.database.base import Base

TENANT = ("organization_id", "workspace_id", "cell_id")
WORKSPACE_COLUMNS = ("workspace_id", "organization_id", "cell_id")
WORKSPACE_TARGET = ("workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id")
GENERATION_TARGET = tuple(f"search_index_generations.{column}" for column in (*TENANT, "id"))
SEARCH_DOCUMENT_TARGET = tuple(f"search_documents.{column}" for column in (*TENANT, "id"))
RESOURCE_TARGET = tuple(f"resources.{column}" for column in (*TENANT, "id"))


class VectorType(UserDefinedType[list[float]]):
    """Minimal pgvector SQLAlchemy type without coupling the domain to an SDK."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "vector"

    def bind_processor(self, dialect: object):
        def process(value: list[float] | None) -> str | None:
            return None if value is None else "[" + ",".join(map(str, value)) + "]"

        return process


class TenantMixin:
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class SearchIndexGeneration(TenantMixin, Base):
    __tablename__ = "search_index_generations"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_search_index_generations"),
        UniqueConstraint(*TENANT, "index_version", name="uq_search_index_generation_version"),
        ForeignKeyConstraint(WORKSPACE_COLUMNS, WORKSPACE_TARGET, ondelete="RESTRICT"),
        CheckConstraint("status IN ('building','active','disabled','retired')"),
        CheckConstraint("dimensions > 0 AND policy_version > 0"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    index_version: Mapped[str] = mapped_column(String(64))
    chunker_version: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(96))
    embedding_version: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="building")
    manifest_digest: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchDocument(TenantMixin, Base):
    __tablename__ = "search_documents"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_search_documents"),
        UniqueConstraint(*TENANT, "generation_id", "identity_digest", name="uq_search_document"),
        ForeignKeyConstraint(WORKSPACE_COLUMNS, WORKSPACE_TARGET, ondelete="RESTRICT"),
        ForeignKeyConstraint(
            (*TENANT, "generation_id"),
            GENERATION_TARGET,
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (*TENANT, "resource_id"),
            RESOURCE_TARGET,
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "source_kind IN ('resource','document_version','document_chunk',"
            "'knowledge_claim','memory_item')"
        ),
        CheckConstraint("status IN ('active','stale','deleted','quarantined')"),
        CheckConstraint("visibility IN ('private','workspace','restricted')"),
        CheckConstraint("classification IN ('public','internal','confidential','restricted')"),
        CheckConstraint("source_version > 0 AND policy_version > 0"),
        CheckConstraint("length(source_digest) = 64 AND length(identity_digest) = 64"),
        Index("ix_search_documents_source", "workspace_id", "source_kind", "source_id"),
        Index("ix_search_documents_resource", "workspace_id", "resource_id", "status"),
        Index("ix_search_documents_fts", "search_vector", postgresql_using="gin"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    generation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_version: Mapped[int] = mapped_column(Integer)
    source_digest: Mapped[str] = mapped_column(String(64))
    identity_digest: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))",
            persisted=True,
        ),
    )
    visibility: Mapped[str] = mapped_column(String(16))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    chunker_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SearchAclProjection(TenantMixin, Base):
    __tablename__ = "search_acl_projections"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_search_acl_projections"),
        UniqueConstraint(
            *TENANT, "document_id", "principal_type", "principal_id", name="uq_search_acl"
        ),
        ForeignKeyConstraint((*TENANT, "document_id"), SEARCH_DOCUMENT_TARGET, ondelete="RESTRICT"),
        CheckConstraint("principal_type IN ('workspace','user')"),
        CheckConstraint("status IN ('active','revoked')"),
        CheckConstraint("policy_version > 0"),
        Index(
            "ix_search_acl_principal", "workspace_id", "principal_type", "principal_id", "status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    principal_type: Mapped[str] = mapped_column(String(16))
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    policy_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    projected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SearchEmbedding(TenantMixin, Base):
    __tablename__ = "search_embeddings"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_search_embeddings"),
        UniqueConstraint(
            *TENANT, "document_id", "model_key", "model_version", name="uq_search_embedding"
        ),
        ForeignKeyConstraint((*TENANT, "document_id"), SEARCH_DOCUMENT_TARGET, ondelete="RESTRICT"),
        CheckConstraint("dimensions > 0"),
        CheckConstraint("length(input_digest) = 64"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    model_key: Mapped[str] = mapped_column(String(96))
    model_version: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(VectorType())
    input_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchReconciliation(TenantMixin, Base):
    __tablename__ = "search_reconciliations"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_search_reconciliations"),
        UniqueConstraint(*TENANT, "idempotency_key", name="uq_search_reconciliation"),
        ForeignKeyConstraint(WORKSPACE_COLUMNS, WORKSPACE_TARGET, ondelete="RESTRICT"),
        CheckConstraint("status IN ('pending','completed','exception')"),
        CheckConstraint("length(input_digest) = 64"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    input_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    exception_detail: Mapped[str | None] = mapped_column(String(512))
    checkpoint: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
