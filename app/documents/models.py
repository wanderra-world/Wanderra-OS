"""Workspace-owned persistence for H3-03 documents and governed derivation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

TENANT = ("organization_id", "workspace_id", "cell_id")
WORKSPACE_COLUMNS = ("workspace_id", "organization_id", "cell_id")
WORKSPACE_TARGET = ("workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id")
DOCUMENT_TARGET = (
    "documents.organization_id",
    "documents.workspace_id",
    "documents.cell_id",
    "documents.id",
)
VERSION_TARGET = (
    "document_versions.organization_id",
    "document_versions.workspace_id",
    "document_versions.cell_id",
    "document_versions.id",
)
DERIVATIVE_TARGET = (
    "document_derivatives.organization_id",
    "document_derivatives.workspace_id",
    "document_derivatives.cell_id",
    "document_derivatives.id",
)


class TenantMixin:
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class Document(TenantMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_documents"),
        UniqueConstraint(*TENANT, "resource_id", name="uq_documents_resource"),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_documents_workspace",
        ),
        ForeignKeyConstraint(
            (*TENANT, "resource_id"),
            (
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ),
            ondelete="RESTRICT",
            name="fk_documents_resource",
        ),
        CheckConstraint("status IN ('active','deleted')", name="ck_documents_status"),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_documents_classification",
        ),
        CheckConstraint("classification_policy_version > 0", name="ck_documents_policy"),
        CheckConstraint("state_version > 0", name="ck_documents_state_version"),
        Index("ix_documents_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    classification: Mapped[str] = mapped_column(String(16))
    classification_policy_version: Mapped[int] = mapped_column(Integer)
    legal_hold: Mapped[bool] = mapped_column(Boolean, server_default="false")
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(TenantMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_document_versions"),
        UniqueConstraint(
            *TENANT, "document_id", "version_number", name="uq_document_versions_number"
        ),
        UniqueConstraint(*TENANT, "document_id", "content_hash", name="uq_document_versions_hash"),
        ForeignKeyConstraint(
            (*TENANT, "document_id"),
            DOCUMENT_TARGET,
            ondelete="RESTRICT",
            name="fk_document_versions_document",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_document_versions_workspace",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_external_reference_id"),
            ("provider_external_references.workspace_id", "provider_external_references.id"),
            ondelete="RESTRICT",
            name="fk_document_versions_external_reference",
        ),
        CheckConstraint("version_number > 0", name="ck_document_versions_number"),
        CheckConstraint("size_bytes > 0", name="ck_document_versions_size"),
        CheckConstraint("length(content_hash) = 64", name="ck_document_versions_hash"),
        CheckConstraint(
            "custody_status IN ('quarantined','verified','rejected','deleted')",
            name="ck_document_versions_custody",
        ),
        CheckConstraint(
            "malware_verdict IN ('pending','clean','infected','error')",
            name="ck_document_versions_malware",
        ),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_document_versions_classification",
        ),
        CheckConstraint(
            "classification_policy_version > 0 AND encryption_key_version > 0",
            name="ck_document_versions_versions",
        ),
        Index("ix_document_versions_document", "workspace_id", "document_id", "version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version_number: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(255))
    quarantine_key: Mapped[str] = mapped_column(String(1024))
    object_key: Mapped[str] = mapped_column(String(1024))
    custody_status: Mapped[str] = mapped_column(String(16), server_default="quarantined")
    malware_verdict: Mapped[str] = mapped_column(String(16), server_default="pending")
    media_type_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    verifier_version: Mapped[str | None] = mapped_column(String(128))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification: Mapped[str] = mapped_column(String(16))
    classification_policy_version: Mapped[int] = mapped_column(Integer)
    encryption_key_version: Mapped[int] = mapped_column(Integer)
    source_external_reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentDerivative(TenantMixin, Base):
    __tablename__ = "document_derivatives"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_document_derivatives"),
        UniqueConstraint(
            *TENANT, "source_version_id", "input_digest", name="uq_document_derivatives_input"
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_version_id"),
            VERSION_TARGET,
            ondelete="RESTRICT",
            name="fk_document_derivatives_version",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_document_derivatives_workspace",
        ),
        CheckConstraint("length(input_digest) = 64", name="ck_document_derivatives_input_digest"),
        CheckConstraint("length(content_hash) = 64", name="ck_document_derivatives_content_hash"),
        CheckConstraint("status IN ('verified','deleted')", name="ck_document_derivatives_status"),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_document_derivatives_classification",
        ),
        CheckConstraint("policy_version > 0", name="ck_document_derivatives_policy"),
        Index("ix_document_derivatives_source", "workspace_id", "source_version_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    derivative_kind: Mapped[str] = mapped_column(String(64))
    processor_key: Mapped[str] = mapped_column(String(96))
    processor_version: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16), server_default="verified")
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    extraction_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(TenantMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_document_chunks"),
        UniqueConstraint(*TENANT, "derivative_id", "position", name="uq_document_chunks_position"),
        ForeignKeyConstraint(
            (*TENANT, "source_version_id"),
            VERSION_TARGET,
            ondelete="RESTRICT",
            name="fk_document_chunks_version",
        ),
        ForeignKeyConstraint(
            (*TENANT, "derivative_id"),
            DERIVATIVE_TARGET,
            ondelete="RESTRICT",
            name="fk_document_chunks_derivative",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_document_chunks_workspace",
        ),
        CheckConstraint("position >= 0", name="ck_document_chunks_position"),
        CheckConstraint("length(content_hash) = 64", name="ck_document_chunks_hash"),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_document_chunks_classification",
        ),
        CheckConstraint("policy_version > 0", name="ck_document_chunks_policy"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    derivative_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentDeletion(TenantMixin, Base):
    __tablename__ = "document_deletions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_document_deletions"),
        ForeignKeyConstraint(
            (*TENANT, "document_id"),
            DOCUMENT_TARGET,
            ondelete="RESTRICT",
            name="fk_document_deletions_document",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_document_deletions_workspace",
        ),
        CheckConstraint(
            "status IN ('pending','blocked','completed','exception')",
            name="ck_document_deletions_status",
        ),
        CheckConstraint(
            "disposition IN ('legal_hold','retention','eligible')",
            name="ck_document_deletions_disposition",
        ),
        Index("ix_document_deletions_document", "workspace_id", "document_id", "requested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    disposition: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(256))
    exception_code: Mapped[str | None] = mapped_column(String(96))
    deletion_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
