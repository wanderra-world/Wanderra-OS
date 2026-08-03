"""Workspace-owned H3-08 workflow and approval persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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


class WorkflowDefinitionRecord(TenantMixin, Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_workflow_definitions"),
        ForeignKeyConstraint(
            WORKSPACE,
            WORKSPACE_TARGET,
            ondelete="RESTRICT",
            name="fk_workflow_definitions_workspace",
        ),
        UniqueConstraint(*TENANT, "name", name="uq_workflow_definitions_name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), server_default="draft")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowDefinitionVersion(TenantMixin, Base):
    __tablename__ = "workflow_definition_versions"
    __table_args__ = (
        PrimaryKeyConstraint(
            *TENANT, "definition_id", "version", name="pk_workflow_definition_versions"
        ),
        ForeignKeyConstraint(
            (*TENANT, "definition_id"),
            (
                "workflow_definitions.organization_id",
                "workflow_definitions.workspace_id",
                "workflow_definitions.cell_id",
                "workflow_definitions.id",
            ),
            ondelete="RESTRICT",
            name="fk_workflow_versions_definition",
        ),
        CheckConstraint("version > 0 AND policy_version > 0", name="ck_workflow_version_positive"),
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    schema_json: Mapped[str] = mapped_column(Text)
    schema_digest: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowInstance(TenantMixin, Base):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_workflow_instances"),
        ForeignKeyConstraint(
            (*TENANT, "definition_id", "definition_version"),
            (
                "workflow_definition_versions.organization_id",
                "workflow_definition_versions.workspace_id",
                "workflow_definition_versions.cell_id",
                "workflow_definition_versions.definition_id",
                "workflow_definition_versions.version",
            ),
            ondelete="RESTRICT",
            name="fk_workflow_instances_version",
        ),
        UniqueConstraint(*TENANT, "idempotency_key", name="uq_workflow_instance_idempotency"),
        CheckConstraint("version > 0", name="ck_workflow_instance_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    definition_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    current_step_key: Mapped[str | None] = mapped_column(String(128))
    state_json: Mapped[str] = mapped_column(Text, server_default="{}")
    input_digest: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    started_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowToken(TenantMixin, Base):
    __tablename__ = "workflow_tokens"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_workflow_tokens"),
        ForeignKeyConstraint(
            (*TENANT, "instance_id"),
            (
                "workflow_instances.organization_id",
                "workflow_instances.workspace_id",
                "workflow_instances.cell_id",
                "workflow_instances.id",
            ),
            ondelete="RESTRICT",
            name="fk_workflow_tokens_instance",
        ),
        UniqueConstraint(*TENANT, "instance_id", "transition_key", name="uq_workflow_transition"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    instance_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    step_key: Mapped[str] = mapped_column(String(128))
    transition_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24))
    input_digest: Mapped[str] = mapped_column(String(64))
    output_digest: Mapped[str | None] = mapped_column(String(64))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowWait(TenantMixin, Base):
    __tablename__ = "workflow_waits"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_workflow_waits"),
        ForeignKeyConstraint(
            (*TENANT, "instance_id"),
            (
                "workflow_instances.organization_id",
                "workflow_instances.workspace_id",
                "workflow_instances.cell_id",
                "workflow_instances.id",
            ),
            ondelete="RESTRICT",
            name="fk_workflow_waits_instance",
        ),
        UniqueConstraint(*TENANT, "resume_key", name="uq_workflow_wait_resume"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    instance_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    step_key: Mapped[str] = mapped_column(String(128))
    resume_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), server_default="waiting")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowApproval(TenantMixin, Base):
    __tablename__ = "workflow_approvals"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_workflow_approvals"),
        ForeignKeyConstraint(
            (*TENANT, "instance_id"),
            (
                "workflow_instances.organization_id",
                "workflow_instances.workspace_id",
                "workflow_instances.cell_id",
                "workflow_instances.id",
            ),
            ondelete="RESTRICT",
            name="fk_workflow_approvals_instance",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    instance_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    step_key: Mapped[str] = mapped_column(String(128))
    action_digest: Mapped[str] = mapped_column(String(64))
    risk: Mapped[str] = mapped_column(String(16))
    required_approvals: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowApprovalDecision(TenantMixin, Base):
    __tablename__ = "workflow_approval_decisions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_workflow_approval_decisions"),
        ForeignKeyConstraint(
            (*TENANT, "approval_id"),
            (
                "workflow_approvals.organization_id",
                "workflow_approvals.workspace_id",
                "workflow_approvals.cell_id",
                "workflow_approvals.id",
            ),
            ondelete="RESTRICT",
            name="fk_workflow_decisions_approval",
        ),
        UniqueConstraint(
            *TENANT, "approval_id", "approver_id", name="uq_workflow_approval_approver"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    approval_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    approver_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    approved: Mapped[bool] = mapped_column(Boolean)
    action_digest: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowReceipt(TenantMixin, Base):
    __tablename__ = "workflow_receipts"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_workflow_receipts"),
        ForeignKeyConstraint(
            (*TENANT, "instance_id"),
            (
                "workflow_instances.organization_id",
                "workflow_instances.workspace_id",
                "workflow_instances.cell_id",
                "workflow_instances.id",
            ),
            ondelete="RESTRICT",
            name="fk_workflow_receipts_instance",
        ),
        UniqueConstraint(
            *TENANT, "instance_id", "transition_key", name="uq_workflow_receipt_transition"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    instance_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    transition_key: Mapped[str] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32))
    action_digest: Mapped[str] = mapped_column(String(64))
    result_digest: Mapped[str | None] = mapped_column(String(64))
    compensation: Mapped[bool] = mapped_column(Boolean, server_default="false")
    uncertain: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
