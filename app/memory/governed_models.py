"""Workspace-owned H3-05 governed-memory persistence."""

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
MEMORY_TARGET = (
    "governed_memory_items.organization_id",
    "governed_memory_items.workspace_id",
    "governed_memory_items.cell_id",
    "governed_memory_items.id",
)


class TenantMixin:
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class GovernedMemoryItem(TenantMixin, Base):
    __tablename__ = "governed_memory_items"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_governed_memory_items"),
        UniqueConstraint(*TENANT, "identity_digest", name="uq_governed_memory_identity"),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_workspace",
        ),
        ForeignKeyConstraint(
            (*TENANT, "subject_resource_id"),
            (
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ),
            ondelete="RESTRICT",
            name="fk_governed_memory_subject",
        ),
        ForeignKeyConstraint(
            (*TENANT, "superseded_by_id"),
            MEMORY_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_superseded_by",
        ),
        CheckConstraint(
            "memory_kind IN ('preference','decision','summary','working_fact')",
            name="ck_governed_memory_kind",
        ),
        CheckConstraint(
            "status IN ('active','superseded','expired','invalidated','deleted')",
            name="ck_governed_memory_status",
        ),
        CheckConstraint(
            "visibility IN ('private','workspace','restricted')",
            name="ck_governed_memory_visibility",
        ),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_governed_memory_classification",
        ),
        CheckConstraint(
            "confidence_basis_points BETWEEN 0 AND 10000",
            name="ck_governed_memory_confidence",
        ),
        CheckConstraint(
            "policy_version > 0 AND state_version > 0", name="ck_governed_memory_versions"
        ),
        CheckConstraint("length(identity_digest) = 64", name="ck_governed_memory_digest"),
        CheckConstraint(
            "(status = 'superseded' AND superseded_by_id IS NOT NULL) OR "
            "(status <> 'superseded' AND superseded_by_id IS NULL)",
            name="ck_governed_memory_supersession",
        ),
        Index("ix_governed_memory_subject", "workspace_id", "subject_resource_id", "status"),
        Index("ix_governed_memory_expiry", "workspace_id", "expires_at", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    memory_kind: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
    identity_digest: Mapped[str] = mapped_column(String(64))
    subject_resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    visibility: Mapped[str] = mapped_column(String(16))
    confidence_basis_points: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    creation_method: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    pinned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    human_confirmed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    processor_key: Mapped[str | None] = mapped_column(String(96))
    processor_version: Mapped[str | None] = mapped_column(String(64))
    input_digest: Mapped[str | None] = mapped_column(String(64))
    state_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GovernedMemorySource(TenantMixin, Base):
    __tablename__ = "governed_memory_sources"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_governed_memory_sources"),
        UniqueConstraint(
            *TENANT,
            "memory_id",
            "source_kind",
            "source_reference_id",
            name="uq_governed_memory_source",
        ),
        ForeignKeyConstraint(
            (*TENANT, "memory_id"),
            MEMORY_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_sources_memory",
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_document_version_id"),
            (
                "document_versions.organization_id",
                "document_versions.workspace_id",
                "document_versions.cell_id",
                "document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_governed_memory_sources_document",
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_claim_id"),
            (
                "knowledge_claims.organization_id",
                "knowledge_claims.workspace_id",
                "knowledge_claims.cell_id",
                "knowledge_claims.id",
            ),
            ondelete="RESTRICT",
            name="fk_governed_memory_sources_claim",
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_resource_id"),
            (
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ),
            ondelete="RESTRICT",
            name="fk_governed_memory_sources_resource",
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_memory_id"),
            MEMORY_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_sources_memory_source",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_sources_workspace",
        ),
        CheckConstraint(
            "source_kind IN ('document_version','knowledge_claim','resource','memory_item')",
            name="ck_governed_memory_sources_kind",
        ),
        CheckConstraint(
            "num_nonnulls(source_document_version_id, source_claim_id, "
            "source_resource_id, source_memory_id) = 1",
            name="ck_governed_memory_sources_one_target",
        ),
        CheckConstraint(
            "(source_kind = 'document_version' "
            "AND source_document_version_id = source_reference_id) OR "
            "(source_kind = 'knowledge_claim' AND source_claim_id = source_reference_id) OR "
            "(source_kind = 'resource' AND source_resource_id = source_reference_id) OR "
            "(source_kind = 'memory_item' AND source_memory_id = source_reference_id)",
            name="ck_governed_memory_sources_target_kind",
        ),
        CheckConstraint("source_version > 0", name="ck_governed_memory_sources_version"),
        CheckConstraint("length(source_digest) = 64", name="ck_governed_memory_sources_digest"),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_governed_memory_sources_classification",
        ),
        CheckConstraint("policy_version > 0", name="ck_governed_memory_sources_policy"),
        Index("ix_governed_memory_sources_reference", "workspace_id", "source_reference_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    memory_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_kind: Mapped[str] = mapped_column(String(24))
    source_reference_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_document_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_memory_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_version: Mapped[int] = mapped_column(Integer)
    source_digest: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GovernedMemoryFeedback(TenantMixin, Base):
    __tablename__ = "governed_memory_feedback"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_governed_memory_feedback"),
        ForeignKeyConstraint(
            (*TENANT, "memory_id"),
            MEMORY_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_feedback_memory",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_feedback_workspace",
        ),
        CheckConstraint(
            "kind IN ('helpful','incorrect','outdated','sensitive')",
            name="ck_governed_memory_feedback_kind",
        ),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_governed_memory_feedback_classification",
        ),
        CheckConstraint("policy_version > 0", name="ck_governed_memory_feedback_policy"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    memory_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(512))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GovernedMemoryDisposition(TenantMixin, Base):
    __tablename__ = "governed_memory_dispositions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_governed_memory_dispositions"),
        UniqueConstraint(*TENANT, "memory_id", "reason", name="uq_governed_memory_disposition"),
        ForeignKeyConstraint(
            (*TENANT, "memory_id"),
            MEMORY_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_dispositions_memory",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_governed_memory_dispositions_workspace",
        ),
        CheckConstraint(
            "reason IN ('expired','source_deleted','permission_revoked','user_deleted',"
            "'workspace_closure','superseded')",
            name="ck_governed_memory_dispositions_reason",
        ),
        CheckConstraint(
            "status IN ('completed','exception')", name="ck_governed_memory_dispositions_status"
        ),
        CheckConstraint(
            "target_status IN ('superseded','expired','invalidated','deleted')",
            name="ck_governed_memory_dispositions_target",
        ),
        CheckConstraint("length(receipt_digest) = 64", name="ck_governed_memory_receipt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    memory_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(24))
    target_status: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    receipt_digest: Mapped[str] = mapped_column(String(64))
    exception_code: Mapped[str | None] = mapped_column(String(96))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
