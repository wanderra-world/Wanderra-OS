"""Workspace-owned H3-04 Knowledge Service and Timeline persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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
CLAIM_TARGET = (
    "knowledge_claims.organization_id",
    "knowledge_claims.workspace_id",
    "knowledge_claims.cell_id",
    "knowledge_claims.id",
)


class TenantMixin:
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class KnowledgeClaim(TenantMixin, Base):
    __tablename__ = "knowledge_claims"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_knowledge_claims"),
        UniqueConstraint(*TENANT, "identity_digest", name="uq_knowledge_claims_identity"),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_knowledge_claims_workspace",
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
            name="fk_knowledge_claims_subject",
        ),
        CheckConstraint(
            "value_type IN ('text','integer','decimal','boolean','instant','uuid')",
            name="ck_knowledge_claims_value_type",
        ),
        CheckConstraint(
            "status IN ('active','contradicted','superseded','invalidated')",
            name="ck_knowledge_claims_status",
        ),
        CheckConstraint(
            "review_state IN ('pending','accepted','rejected')",
            name="ck_knowledge_claims_review",
        ),
        CheckConstraint(
            "confidence_basis_points BETWEEN 0 AND 10000", name="ck_knowledge_claims_confidence"
        ),
        CheckConstraint("length(identity_digest) = 64", name="ck_knowledge_claims_digest"),
        CheckConstraint(
            "length(derivation_digest) = 64",
            name="ck_knowledge_claims_derivation_digest",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_knowledge_claims_validity",
        ),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_knowledge_claims_classification",
        ),
        CheckConstraint(
            "policy_version > 0 AND state_version > 0", name="ck_knowledge_claims_versions"
        ),
        Index("ix_knowledge_claims_subject", "workspace_id", "subject_resource_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    subject_resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    predicate: Mapped[str] = mapped_column(String(160))
    value_type: Mapped[str] = mapped_column(String(16))
    canonical_value: Mapped[str] = mapped_column(Text)
    identity_digest: Mapped[str] = mapped_column(String(64))
    derivation_digest: Mapped[str] = mapped_column(String(64))
    confidence_basis_points: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    review_state: Mapped[str] = mapped_column(String(16), server_default="pending")
    review_reason: Mapped[str | None] = mapped_column(String(256))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extractor_key: Mapped[str] = mapped_column(String(96))
    extractor_version: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeEvidence(TenantMixin, Base):
    __tablename__ = "knowledge_evidence"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_knowledge_evidence"),
        UniqueConstraint(
            *TENANT,
            "claim_id",
            "source_version_id",
            "span_start",
            "span_end",
            name="uq_knowledge_evidence_span",
        ),
        ForeignKeyConstraint(
            (*TENANT, "claim_id"),
            CLAIM_TARGET,
            ondelete="RESTRICT",
            name="fk_knowledge_evidence_claim",
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_version_id"),
            (
                "document_versions.organization_id",
                "document_versions.workspace_id",
                "document_versions.cell_id",
                "document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_knowledge_evidence_version",
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_chunk_id"),
            (
                "document_chunks.organization_id",
                "document_chunks.workspace_id",
                "document_chunks.cell_id",
                "document_chunks.id",
            ),
            ondelete="RESTRICT",
            name="fk_knowledge_evidence_chunk",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_knowledge_evidence_workspace",
        ),
        CheckConstraint("length(source_hash) = 64", name="ck_knowledge_evidence_hash"),
        CheckConstraint(
            "span_start >= 0 AND span_end > span_start", name="ck_knowledge_evidence_span"
        ),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_knowledge_evidence_classification",
        ),
        CheckConstraint("policy_version > 0", name="ck_knowledge_evidence_policy"),
        Index("ix_knowledge_evidence_source", "workspace_id", "source_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_hash: Mapped[str] = mapped_column(String(64))
    span_start: Mapped[int] = mapped_column(Integer)
    span_end: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeRelation(TenantMixin, Base):
    __tablename__ = "knowledge_relations"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_knowledge_relations"),
        UniqueConstraint(
            *TENANT,
            "claim_id",
            "conflicting_claim_id",
            "relation_type",
            name="uq_knowledge_relations_pair",
        ),
        ForeignKeyConstraint(
            (*TENANT, "claim_id"),
            CLAIM_TARGET,
            ondelete="RESTRICT",
            name="fk_knowledge_relations_claim",
        ),
        ForeignKeyConstraint(
            (*TENANT, "conflicting_claim_id"),
            CLAIM_TARGET,
            ondelete="RESTRICT",
            name="fk_knowledge_relations_conflict",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_knowledge_relations_workspace",
        ),
        CheckConstraint("claim_id <> conflicting_claim_id", name="ck_knowledge_relations_distinct"),
        CheckConstraint(
            "relation_type IN ('contradicts','supersedes')", name="ck_knowledge_relations_type"
        ),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_knowledge_relations_classification",
        ),
        CheckConstraint("policy_version > 0", name="ck_knowledge_relations_policy"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    conflicting_claim_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    relation_type: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(256))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeSourceDisposition(TenantMixin, Base):
    __tablename__ = "knowledge_source_dispositions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_knowledge_source_dispositions"),
        UniqueConstraint(
            *TENANT,
            "source_version_id",
            name="uq_knowledge_source_dispositions_source",
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_version_id"),
            (
                "document_versions.organization_id",
                "document_versions.workspace_id",
                "document_versions.cell_id",
                "document_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_knowledge_source_dispositions_version",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_knowledge_source_dispositions_workspace",
        ),
        CheckConstraint(
            "status IN ('pending','completed','exception')",
            name="ck_knowledge_source_dispositions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    exception_code: Mapped[str | None] = mapped_column(String(96))
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TimelineEntry(TenantMixin, Base):
    __tablename__ = "timeline_entries"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_timeline_entries"),
        UniqueConstraint(*TENANT, "source_event_id", name="uq_timeline_entries_source"),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_timeline_entries_workspace",
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
            name="fk_timeline_entries_resource",
        ),
        ForeignKeyConstraint(
            (*TENANT, "source_claim_id"),
            CLAIM_TARGET,
            ondelete="RESTRICT",
            name="fk_timeline_entries_claim",
        ),
        CheckConstraint(
            "source_sequence > 0 AND projection_version > 0", name="ck_timeline_entries_versions"
        ),
        CheckConstraint(
            "visibility IN ('workspace','restricted')", name="ck_timeline_entries_visibility"
        ),
        CheckConstraint("status IN ('active','removed')", name="ck_timeline_entries_status"),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_timeline_entries_classification",
        ),
        CheckConstraint("policy_version > 0", name="ck_timeline_entries_policy"),
        Index(
            "ix_timeline_entries_order",
            "workspace_id",
            "occurred_at",
            "source_sequence",
            "source_event_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    projection_key: Mapped[str] = mapped_column(String(96))
    source_event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_event_type: Mapped[str] = mapped_column(String(128))
    source_sequence: Mapped[int] = mapped_column(Integer)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(512))
    visibility: Mapped[str] = mapped_column(String(16))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    projection_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TimelineCheckpoint(TenantMixin, Base):
    __tablename__ = "timeline_checkpoints"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "projection_key", name="pk_timeline_checkpoints"),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_timeline_checkpoints_workspace",
        ),
        CheckConstraint("projection_version > 0", name="ck_timeline_checkpoints_version"),
        CheckConstraint("length(checksum) = 64", name="ck_timeline_checkpoints_checksum"),
    )

    projection_key: Mapped[str] = mapped_column(String(96))
    projection_version: Mapped[int] = mapped_column(Integer)
    entry_count: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    last_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_source_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
