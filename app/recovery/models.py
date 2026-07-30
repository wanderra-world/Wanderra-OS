"""Tenant-owned recovery, governance, export, and closure evidence."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WorkspaceDataGovernance(Base):
    __tablename__ = "workspace_data_governance"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            name="pk_workspace_data_governance",
        ),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_workspace_data_governance_workspace",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    legal_hold: Mapped[bool] = mapped_column(Boolean, server_default="false")
    legal_hold_reason: Mapped[str | None] = mapped_column(Text)
    minimum_retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    policy_version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkspaceExport(Base):
    __tablename__ = "workspace_exports"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_workspace_exports"),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_workspace_exports_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_workspace_exports_idempotency",
        ),
        Index("ix_workspace_exports_created", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB)
    manifest_digest: Mapped[str] = mapped_column(String(64))
    provider_reconciliation_required: Mapped[bool] = mapped_column(
        Boolean, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkspaceClosure(Base):
    __tablename__ = "workspace_closures"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_workspace_closures"),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_workspace_closures_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_workspace_closures_idempotency",
        ),
        CheckConstraint(
            "state IN ('writes_frozen', 'retention_blocked', 'erasing', "
            "'closed', 'failed')",
            name="ck_workspace_closures_state",
        ),
        Index("ix_workspace_closures_state", "workspace_id", "state"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32))
    initiated_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    authorization_decision_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(Text)
    blocked_reason: Mapped[str | None] = mapped_column(String(96))
    before_manifest: Mapped[dict[str, object]] = mapped_column(JSONB)
    after_manifest: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    provider_reconciliation_required: Mapped[bool] = mapped_column(
        Boolean, server_default="true"
    )
    receipt_digest: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecoveryEvidence(Base):
    __tablename__ = "workspace_recovery_evidence"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "backup_id",
            "operation",
            name="pk_workspace_recovery_evidence",
        ),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_workspace_recovery_evidence_workspace",
        ),
        CheckConstraint(
            "operation IN ('backup', 'restore', 'key_recovery')",
            name="ck_workspace_recovery_operation",
        ),
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_workspace_recovery_status",
        ),
        Index(
            "ix_workspace_recovery_recorded",
            "workspace_id",
            "recorded_at",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    backup_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    operation: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    isolated_target: Mapped[str | None] = mapped_column(String(255))
    source_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    recovery_point_seconds: Mapped[int | None] = mapped_column(Integer)
    recovery_time_seconds: Mapped[int | None] = mapped_column(Integer)
    counts_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    digests_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    key_access_verified: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )
    failure_code: Mapped[str | None] = mapped_column(String(96))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
