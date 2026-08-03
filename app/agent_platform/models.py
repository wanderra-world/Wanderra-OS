"""Workspace-owned H3-10 agent platform persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


def workspace_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(WORKSPACE, WORKSPACE_TARGET, ondelete="RESTRICT", name=name)


class AgentManifestRecord(TenantMixin, Base):
    __tablename__ = "agent_manifests"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_agent_manifests"),
        UniqueConstraint(*TENANT, "name", name="uq_agent_manifest_name"),
        workspace_fk("fk_agent_manifests_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(128))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentManifestVersion(TenantMixin, Base):
    __tablename__ = "agent_manifest_versions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "manifest_id", "version", name="pk_agent_manifest_versions"),
        ForeignKeyConstraint(
            (*TENANT, "manifest_id"),
            (
                "agent_manifests.organization_id",
                "agent_manifests.workspace_id",
                "agent_manifests.cell_id",
                "agent_manifests.id",
            ),
            ondelete="RESTRICT",
            name="fk_agent_manifest_versions_manifest",
        ),
    )
    manifest_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    manifest_json: Mapped[str] = mapped_column(Text)
    manifest_digest: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentToolRecord(TenantMixin, Base):
    __tablename__ = "agent_tools"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_agent_tools"),
        UniqueConstraint(*TENANT, "tool_key", name="uq_agent_tool_key"),
        workspace_fk("fk_agent_tools_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tool_key: Mapped[str] = mapped_column(String(128))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentToolVersion(TenantMixin, Base):
    __tablename__ = "agent_tool_versions"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "tool_id", "version", name="pk_agent_tool_versions"),
        ForeignKeyConstraint(
            (*TENANT, "tool_id"),
            (
                "agent_tools.organization_id",
                "agent_tools.workspace_id",
                "agent_tools.cell_id",
                "agent_tools.id",
            ),
            ondelete="RESTRICT",
            name="fk_agent_tool_versions_tool",
        ),
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    tool_json: Mapped[str] = mapped_column(Text)
    tool_digest: Mapped[str] = mapped_column(String(64))
    risk: Mapped[str] = mapped_column(String(16))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentDelegation(TenantMixin, Base):
    __tablename__ = "agent_delegations"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_agent_delegations"),
        UniqueConstraint(*TENANT, "delegation_digest", name="uq_agent_delegation_digest"),
        workspace_fk("fk_agent_delegations_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    parent_delegation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    permissions_json: Mapped[str] = mapped_column(Text)
    risk_ceiling: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delegation_digest: Mapped[str] = mapped_column(String(64))


class AgentPlan(TenantMixin, Base):
    __tablename__ = "agent_plans"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", "version", name="pk_agent_plans"),
        ForeignKeyConstraint(
            (*TENANT, "manifest_id", "manifest_version"),
            (
                "agent_manifest_versions.organization_id",
                "agent_manifest_versions.workspace_id",
                "agent_manifest_versions.cell_id",
                "agent_manifest_versions.manifest_id",
                "agent_manifest_versions.version",
            ),
            ondelete="RESTRICT",
            name="fk_agent_plans_manifest_version",
        ),
        UniqueConstraint(*TENANT, "idempotency_key", name="uq_agent_plan_idempotency"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    manifest_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    manifest_version: Mapped[int] = mapped_column(Integer)
    plan_json: Mapped[str] = mapped_column(Text)
    plan_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    classification: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentPlanStep(TenantMixin, Base):
    __tablename__ = "agent_plan_steps"
    __table_args__ = (
        PrimaryKeyConstraint(
            *TENANT, "plan_id", "plan_version", "step_key", name="pk_agent_plan_steps"
        ),
        ForeignKeyConstraint(
            (*TENANT, "plan_id", "plan_version"),
            (
                "agent_plans.organization_id",
                "agent_plans.workspace_id",
                "agent_plans.cell_id",
                "agent_plans.id",
                "agent_plans.version",
            ),
            ondelete="RESTRICT",
            name="fk_agent_plan_steps_plan",
        ),
        ForeignKeyConstraint(
            (*TENANT, "tool_id", "tool_version"),
            (
                "agent_tool_versions.organization_id",
                "agent_tool_versions.workspace_id",
                "agent_tool_versions.cell_id",
                "agent_tool_versions.tool_id",
                "agent_tool_versions.version",
            ),
            ondelete="RESTRICT",
            name="fk_agent_plan_steps_tool_version",
        ),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_version: Mapped[int] = mapped_column(Integer)
    step_key: Mapped[str] = mapped_column(String(128))
    tool_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tool_key: Mapped[str] = mapped_column(String(128))
    tool_version: Mapped[int] = mapped_column(Integer)
    step_json: Mapped[str] = mapped_column(Text)
    action_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))


class AgentBudgetReservation(TenantMixin, Base):
    __tablename__ = "agent_budget_reservations"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_agent_budget_reservations"),
        UniqueConstraint(*TENANT, "idempotency_key", name="uq_agent_budget_idempotency"),
        ForeignKeyConstraint(
            (*TENANT, "manifest_id", "manifest_version"),
            (
                "agent_manifest_versions.organization_id",
                "agent_manifest_versions.workspace_id",
                "agent_manifest_versions.cell_id",
                "agent_manifest_versions.manifest_id",
                "agent_manifest_versions.version",
            ),
            ondelete="RESTRICT",
            name="fk_agent_budget_manifest_version",
        ),
        ForeignKeyConstraint(
            (*TENANT, "plan_id", "plan_version"),
            (
                "agent_plans.organization_id",
                "agent_plans.workspace_id",
                "agent_plans.cell_id",
                "agent_plans.id",
                "agent_plans.version",
            ),
            ondelete="RESTRICT",
            name="fk_agent_budget_plan",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    manifest_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    manifest_version: Mapped[int] = mapped_column(Integer)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_version: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int] = mapped_column(Integer)
    cost_micros: Mapped[int] = mapped_column(Integer)
    tool_calls: Mapped[int] = mapped_column(Integer)
    seconds: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentOrchestration(TenantMixin, Base):
    __tablename__ = "agent_orchestrations"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_agent_orchestrations"),
        ForeignKeyConstraint(
            (*TENANT, "plan_id", "plan_version"),
            (
                "agent_plans.organization_id",
                "agent_plans.workspace_id",
                "agent_plans.cell_id",
                "agent_plans.id",
                "agent_plans.version",
            ),
            ondelete="RESTRICT",
            name="fk_agent_orchestrations_plan",
        ),
        ForeignKeyConstraint(
            (*TENANT, "delegation_id"),
            (
                "agent_delegations.organization_id",
                "agent_delegations.workspace_id",
                "agent_delegations.cell_id",
                "agent_delegations.id",
            ),
            ondelete="RESTRICT",
            name="fk_agent_orchestrations_delegation",
        ),
        UniqueConstraint(*TENANT, "idempotency_key", name="uq_agent_orchestration_idempotency"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    plan_version: Mapped[int] = mapped_column(Integer)
    delegation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24))
    current_step_key: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentExecutionReceipt(TenantMixin, Base):
    __tablename__ = "agent_execution_receipts"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_agent_execution_receipts"),
        ForeignKeyConstraint(
            (*TENANT, "orchestration_id"),
            (
                "agent_orchestrations.organization_id",
                "agent_orchestrations.workspace_id",
                "agent_orchestrations.cell_id",
                "agent_orchestrations.id",
            ),
            ondelete="RESTRICT",
            name="fk_agent_receipts_orchestration",
        ),
        UniqueConstraint(*TENANT, "orchestration_id", "step_key", name="uq_agent_receipt_step"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    orchestration_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    step_key: Mapped[str] = mapped_column(String(128))
    command_receipt_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action_digest: Mapped[str] = mapped_column(String(64))
    result_digest: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(24))
    verified: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentEvaluationRun(TenantMixin, Base):
    __tablename__ = "agent_evaluation_runs"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_agent_evaluation_runs"),
        UniqueConstraint(*TENANT, "run_key", name="uq_agent_evaluation_run_key"),
        ForeignKeyConstraint(
            (*TENANT, "manifest_id", "manifest_version"),
            (
                "agent_manifest_versions.organization_id",
                "agent_manifest_versions.workspace_id",
                "agent_manifest_versions.cell_id",
                "agent_manifest_versions.manifest_id",
                "agent_manifest_versions.version",
            ),
            ondelete="RESTRICT",
            name="fk_agent_evaluation_manifest_version",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    run_key: Mapped[str] = mapped_column(String(128))
    manifest_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    manifest_version: Mapped[int] = mapped_column(Integer)
    evaluation_set_key: Mapped[str] = mapped_column(String(128))
    result_digest: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
