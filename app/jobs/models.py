"""Workspace-owned persistence for H3-02 durable execution."""

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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

TENANT = ("organization_id", "workspace_id", "cell_id")
WORKSPACE_COLUMNS = ("workspace_id", "organization_id", "cell_id")
WORKSPACE_TARGET = ("workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id")
DEFINITION_TARGET = (
    "job_definitions.organization_id",
    "job_definitions.workspace_id",
    "job_definitions.cell_id",
    "job_definitions.id",
)
JOB_TARGET = (
    "job_instances.organization_id",
    "job_instances.workspace_id",
    "job_instances.cell_id",
    "job_instances.id",
)


class TenantMixin:
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class JobDefinition(TenantMixin, Base):
    __tablename__ = "job_definitions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_job_definitions"),
        UniqueConstraint(
            *TENANT, "definition_key", "definition_version", name="uq_job_definitions_key_version"
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_job_definitions_workspace",
        ),
        CheckConstraint("definition_version > 0", name="ck_job_definitions_version"),
        CheckConstraint("max_attempts BETWEEN 1 AND 5", name="ck_job_definitions_attempts"),
        CheckConstraint("max_concurrency BETWEEN 1 AND 20", name="ck_job_definitions_concurrency"),
        CheckConstraint("rate_limit_per_minute BETWEEN 1 AND 120", name="ck_job_definitions_rate"),
        CheckConstraint(
            "status IN ('active','paused','retired')", name="ck_job_definitions_status"
        ),
        Index("ix_job_definitions_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    definition_key: Mapped[str] = mapped_column(String(96))
    definition_version: Mapped[int] = mapped_column(Integer)
    handler_key: Mapped[str] = mapped_column(String(128))
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="5")
    retry_delays: Mapped[list[int]] = mapped_column(JSONB)
    max_concurrency: Mapped[int] = mapped_column(Integer, server_default="20")
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, server_default="120")
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    state_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobInstance(TenantMixin, Base):
    __tablename__ = "job_instances"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_job_instances"),
        UniqueConstraint(
            *TENANT, "definition_id", "idempotency_key", name="uq_job_instances_idempotency"
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_job_instances_workspace",
        ),
        ForeignKeyConstraint(
            (*TENANT, "definition_id"),
            DEFINITION_TARGET,
            ondelete="RESTRICT",
            name="fk_job_instances_definition",
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
            name="fk_job_instances_resource",
        ),
        ForeignKeyConstraint(
            (*TENANT, "replay_of_job_id"),
            JOB_TARGET,
            ondelete="RESTRICT",
            name="fk_job_instances_replay_source",
        ),
        CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','cancelled',"
            "'dead_lettered','expired')",
            name="ck_job_instances_status",
        ),
        CheckConstraint("attempt_count BETWEEN 0 AND 5", name="ck_job_instances_attempt_count"),
        CheckConstraint("state_version > 0", name="ck_job_instances_state_version"),
        CheckConstraint("deadline > available_at", name="ck_job_instances_deadline"),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_job_instances_classification",
        ),
        Index("ix_job_instances_claim", "workspace_id", "status", "available_at", "created_at"),
        Index("ix_job_instances_lease", "workspace_id", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    command_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    classification: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), server_default="queued")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(256))
    replay_of_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    correlation_id: Mapped[str] = mapped_column(String(128))
    state_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_digest: Mapped[str | None] = mapped_column(String(64))


class JobAttempt(TenantMixin, Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_job_attempts"),
        UniqueConstraint(*TENANT, "job_id", "attempt_number", name="uq_job_attempts_number"),
        ForeignKeyConstraint(
            (*TENANT, "job_id"), JOB_TARGET, ondelete="RESTRICT", name="fk_job_attempts_job"
        ),
        CheckConstraint("attempt_number BETWEEN 1 AND 5", name="ck_job_attempts_number"),
        CheckConstraint(
            "status IN ('running','succeeded','failed','abandoned','cancelled')",
            name="ck_job_attempts_status",
        ),
        Index("ix_job_attempts_job", "workspace_id", "job_id", "attempt_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_number: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), server_default="running")
    failure_category: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(96))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobDeadLetter(TenantMixin, Base):
    __tablename__ = "job_dead_letters"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_job_dead_letters"),
        UniqueConstraint(*TENANT, "job_id", name="uq_job_dead_letters_job"),
        ForeignKeyConstraint(
            (*TENANT, "job_id"), JOB_TARGET, ondelete="RESTRICT", name="fk_job_dead_letters_job"
        ),
        ForeignKeyConstraint(
            (*TENANT, "replay_job_id"),
            JOB_TARGET,
            ondelete="RESTRICT",
            name="fk_job_dead_letters_replay_job",
        ),
        CheckConstraint("status IN ('open','replayed')", name="ck_job_dead_letters_status"),
        Index("ix_job_dead_letters_status", "workspace_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    failure_category: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(16), server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replayed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    replay_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    replay_reason: Mapped[str | None] = mapped_column(String(256))


class JobSchedule(TenantMixin, Base):
    __tablename__ = "job_schedules"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_job_schedules"),
        ForeignKeyConstraint(
            (*TENANT, "definition_id"),
            DEFINITION_TARGET,
            ondelete="RESTRICT",
            name="fk_job_schedules_definition",
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_job_schedules_workspace",
        ),
        CheckConstraint(
            "schedule_kind IN ('once','interval','daily_local')", name="ck_job_schedules_kind"
        ),
        CheckConstraint(
            "misfire_policy IN ('skip','fire_once','catch_up')", name="ck_job_schedules_misfire"
        ),
        CheckConstraint(
            "status IN ('active','paused','completed')", name="ck_job_schedules_status"
        ),
        Index("ix_job_schedules_due", "workspace_id", "status", "next_due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    schedule_kind: Mapped[str] = mapped_column(String(24))
    misfire_policy: Mapped[str] = mapped_column(String(16))
    first_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str | None] = mapped_column(String(64))
    local_hour: Mapped[int | None] = mapped_column(Integer)
    local_minute: Mapped[int | None] = mapped_column(Integer)
    local_time_policy: Mapped[str | None] = mapped_column(String(16))
    command_type: Mapped[str] = mapped_column(String(128))
    command_payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    idempotency_prefix: Mapped[str] = mapped_column(String(96))
    job_deadline_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobOperatorControl(TenantMixin, Base):
    __tablename__ = "job_operator_controls"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_job_operator_controls"),
        UniqueConstraint(
            *TENANT, "scope_type", "scope_reference", name="uq_job_operator_controls_scope"
        ),
        ForeignKeyConstraint(
            WORKSPACE_COLUMNS,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_job_operator_controls_workspace",
        ),
        CheckConstraint(
            "scope_type IN ('workspace','definition')", name="ck_job_operator_controls_scope"
        ),
        CheckConstraint("state_version > 0", name="ck_job_operator_controls_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_reference: Mapped[str] = mapped_column(String(128))
    paused: Mapped[bool] = mapped_column(Boolean, server_default="false")
    reason: Mapped[str] = mapped_column(String(256))
    state_version: Mapped[int] = mapped_column(Integer, server_default="1")
    changed_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
