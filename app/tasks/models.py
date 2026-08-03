"""Workspace-owned canonical H3-07 task persistence."""

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
WORKSPACE = ("workspace_id", "organization_id", "cell_id")
WORKSPACE_TARGET = ("workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id")
TASK_TARGET = ("tasks.organization_id", "tasks.workspace_id", "tasks.cell_id", "tasks.id")


class TenantMixin:
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class Task(TenantMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_tasks"),
        UniqueConstraint(*TENANT, "resource_id", name="uq_tasks_resource"),
        ForeignKeyConstraint(
            WORKSPACE, WORKSPACE_TARGET, ondelete="RESTRICT", name="fk_tasks_workspace"
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
            name="fk_tasks_resource",
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
            name="fk_tasks_source",
        ),
        CheckConstraint(
            "status IN ('open','in_progress','blocked','completed','cancelled','deleted')",
            name="ck_tasks_status",
        ),
        CheckConstraint("priority IN ('low','normal','high','urgent')", name="ck_tasks_priority"),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_tasks_classification",
        ),
        CheckConstraint("version > 0 AND policy_version > 0", name="ck_tasks_versions"),
        Index("ix_tasks_workspace_status_due", "workspace_id", "status", "due_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(String(24), server_default="open")
    priority: Mapped[str] = mapped_column(String(16), server_default="normal")
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str | None] = mapped_column(String(64))
    recurrence_reference: Mapped[str | None] = mapped_column(String(128))
    source_resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    completion_evidence_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskParticipant(TenantMixin, Base):
    __tablename__ = "task_participants"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "task_id", "user_id", "kind", name="pk_task_participants"),
        ForeignKeyConstraint(
            (*TENANT, "task_id"), TASK_TARGET, ondelete="RESTRICT", name="fk_task_participants_task"
        ),
        ForeignKeyConstraint(
            ("workspace_id", "user_id"),
            ("workspace_memberships.workspace_id", "workspace_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_task_participants_membership",
        ),
        CheckConstraint("kind IN ('assignee','watcher')", name="ck_task_participants_kind"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    added_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskDependency(TenantMixin, Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "task_id", "depends_on_task_id", name="pk_task_dependencies"),
        ForeignKeyConstraint(
            (*TENANT, "task_id"), TASK_TARGET, ondelete="RESTRICT", name="fk_task_dependencies_task"
        ),
        ForeignKeyConstraint(
            (*TENANT, "depends_on_task_id"),
            TASK_TARGET,
            ondelete="RESTRICT",
            name="fk_task_dependencies_target",
        ),
        CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dependencies_distinct"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskComment(TenantMixin, Base):
    __tablename__ = "task_comments"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_task_comments"),
        ForeignKeyConstraint(
            (*TENANT, "task_id"), TASK_TARGET, ondelete="RESTRICT", name="fk_task_comments_task"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskCompletionEvidence(TenantMixin, Base):
    __tablename__ = "task_completion_evidence"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_task_completion_evidence"),
        ForeignKeyConstraint(
            (*TENANT, "task_id"), TASK_TARGET, ondelete="RESTRICT", name="fk_task_evidence_task"
        ),
        ForeignKeyConstraint(
            (*TENANT, "evidence_resource_id"),
            (
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ),
            ondelete="RESTRICT",
            name="fk_task_evidence_resource",
        ),
        ForeignKeyConstraint(
            (*TENANT, "supersedes_evidence_id"),
            (
                "task_completion_evidence.organization_id",
                "task_completion_evidence.workspace_id",
                "task_completion_evidence.cell_id",
                "task_completion_evidence.id",
            ),
            ondelete="RESTRICT",
            name="fk_task_evidence_supersedes",
        ),
        UniqueConstraint(*TENANT, "task_id", "evidence_digest", name="uq_task_evidence_digest"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    evidence_resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    evidence_digest: Mapped[str] = mapped_column(String(64))
    statement: Mapped[str] = mapped_column(Text)
    supersedes_evidence_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskExternalReference(TenantMixin, Base):
    __tablename__ = "task_external_references"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_task_external_references"),
        ForeignKeyConstraint(
            (*TENANT, "task_id"), TASK_TARGET, ondelete="RESTRICT", name="fk_task_external_task"
        ),
        UniqueConstraint(*TENANT, "authority", "external_id", name="uq_task_external_authority"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    authority: Mapped[str] = mapped_column(String(96))
    external_id: Mapped[str] = mapped_column(String(256))
    external_version: Mapped[str | None] = mapped_column(String(128))
    linked_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskReminder(TenantMixin, Base):
    __tablename__ = "task_reminders"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_task_reminders"),
        ForeignKeyConstraint(
            (*TENANT, "task_id"), TASK_TARGET, ondelete="RESTRICT", name="fk_task_reminders_task"
        ),
        ForeignKeyConstraint(
            (*TENANT, "job_id"),
            (
                "job_instances.organization_id",
                "job_instances.workspace_id",
                "job_instances.cell_id",
                "job_instances.id",
            ),
            ondelete="RESTRICT",
            name="fk_task_reminders_job",
        ),
        UniqueConstraint(*TENANT, "identity_key", name="uq_task_reminder_identity"),
        CheckConstraint(
            "status IN ('scheduled','cancelled','dispatched')", name="ck_task_reminders_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    identity_key: Mapped[str] = mapped_column(String(128))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="scheduled")
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
