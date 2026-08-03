"""Workspace-owned H3-11 observation and operator evidence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKeyConstraint,
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
WORKSPACE = ("workspace_id", "organization_id", "cell_id")
WORKSPACE_TARGET = ("workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id")


class TenantMixin:
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)


def workspace_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(WORKSPACE, WORKSPACE_TARGET, ondelete="RESTRICT", name=name)


class PlatformTelemetryRecord(TenantMixin, Base):
    __tablename__ = "platform_telemetry_records"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_platform_telemetry_records"),
        UniqueConstraint(*TENANT, "record_key", name="uq_platform_telemetry_record_key"),
        workspace_fk("fk_platform_telemetry_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    record_key: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[int] = mapped_column(Integer)
    signal_key: Mapped[str] = mapped_column(String(128))
    correlation_id: Mapped[str] = mapped_column(String(128))
    classification: Mapped[str] = mapped_column(String(16))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    labels_json: Mapped[str] = mapped_column(Text)
    evidence_digest: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformEvaluationRun(TenantMixin, Base):
    __tablename__ = "platform_evaluation_runs"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_platform_evaluation_runs"),
        UniqueConstraint(*TENANT, "run_key", name="uq_platform_evaluation_run_key"),
        workspace_fk("fk_platform_evaluation_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    run_key: Mapped[str] = mapped_column(String(128))
    dataset_key: Mapped[str] = mapped_column(String(128))
    dataset_version: Mapped[int] = mapped_column(Integer)
    commit_sha: Mapped[str] = mapped_column(String(40))
    result_digest: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    critical_findings: Mapped[int] = mapped_column(Integer)
    high_findings: Mapped[int] = mapped_column(Integer)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlatformOperatorAction(TenantMixin, Base):
    __tablename__ = "platform_operator_actions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_platform_operator_actions"),
        UniqueConstraint(*TENANT, "idempotency_key", name="uq_platform_operator_idempotency"),
        workspace_fk("fk_platform_operator_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(24))
    scope_type: Mapped[str] = mapped_column(String(24))
    scope_reference: Mapped[str] = mapped_column(String(128))
    expected_version: Mapped[int] = mapped_column(Integer, server_default="0")
    reason: Mapped[str] = mapped_column(String(256))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformRecoveryDrill(TenantMixin, Base):
    __tablename__ = "platform_recovery_drills"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_platform_recovery_drills"),
        UniqueConstraint(*TENANT, "drill_key", name="uq_platform_recovery_drill_key"),
        workspace_fk("fk_platform_recovery_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    drill_key: Mapped[str] = mapped_column(String(128))
    drill_type: Mapped[str] = mapped_column(String(24))
    artifact_digest: Mapped[str] = mapped_column(String(64))
    restored_digest: Mapped[str] = mapped_column(String(64))
    rpo_seconds: Mapped[int] = mapped_column(Integer)
    rto_seconds: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
