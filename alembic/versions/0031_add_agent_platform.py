"""Add provider-neutral H3-10 agent platform state.

Revision ID: 0031_h3_agent_platform
Revises: 0030_h3_notification_center
"""

# ruff: noqa: E501
from collections.abc import Sequence

from alembic import op

revision = "0031_h3_agent_platform"
down_revision = "0030_h3_notification_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "agent_manifests",
    "agent_manifest_versions",
    "agent_tools",
    "agent_tool_versions",
    "agent_delegations",
    "agent_plans",
    "agent_plan_steps",
    "agent_budget_reservations",
    "agent_orchestrations",
    "agent_execution_receipts",
    "agent_evaluation_runs",
)
TENANT = "organization_id UUID NOT NULL, workspace_id UUID NOT NULL, cell_id UUID NOT NULL"
WORKSPACE_FK = "FOREIGN KEY (workspace_id,organization_id,cell_id) REFERENCES workspaces(workspace_id,organization_id,cell_id) ON DELETE RESTRICT"


def secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    predicate = "workspace_id=NULLIF(current_setting('atlas.workspace_id',TRUE),'')::UUID AND organization_id=NULLIF(current_setting('atlas.organization_id',TRUE),'')::UUID AND cell_id=NULLIF(current_setting('atlas.cell_id',TRUE),'')::UUID"
    op.execute(
        f"CREATE POLICY {table}_workspace_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})"
    )
    op.execute(
        f"CREATE TRIGGER {table}_workspace_writable BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()"
    )


def upgrade() -> None:
    op.execute(
        f"""CREATE TABLE agent_manifests ({TENANT}, id UUID NOT NULL, name VARCHAR(128) NOT NULL, owner_user_id UUID NOT NULL, enabled BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,name), {WORKSPACE_FK})"""
    )
    op.execute(
        f"""CREATE TABLE agent_manifest_versions ({TENANT}, manifest_id UUID NOT NULL, version INTEGER NOT NULL CHECK(version>0), manifest_json TEXT NOT NULL, manifest_digest VARCHAR(64) NOT NULL, classification VARCHAR(16) NOT NULL, policy_version INTEGER NOT NULL CHECK(policy_version>0), activated_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,manifest_id,version), FOREIGN KEY (organization_id,workspace_id,cell_id,manifest_id) REFERENCES agent_manifests(organization_id,workspace_id,cell_id,id) ON DELETE RESTRICT)"""
    )
    op.execute(
        f"""CREATE TABLE agent_tools ({TENANT}, id UUID NOT NULL, tool_key VARCHAR(128) NOT NULL, owner_user_id UUID NOT NULL, enabled BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,tool_key), {WORKSPACE_FK})"""
    )
    op.execute(
        f"""CREATE TABLE agent_tool_versions ({TENANT}, tool_id UUID NOT NULL, version INTEGER NOT NULL CHECK(version>0), tool_json TEXT NOT NULL, tool_digest VARCHAR(64) NOT NULL, risk VARCHAR(16) NOT NULL, activated_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,tool_id,version), FOREIGN KEY (organization_id,workspace_id,cell_id,tool_id) REFERENCES agent_tools(organization_id,workspace_id,cell_id,id) ON DELETE RESTRICT)"""
    )
    op.execute(
        f"""CREATE TABLE agent_delegations ({TENANT}, id UUID NOT NULL, actor_id UUID NOT NULL, parent_delegation_id UUID, permissions_json TEXT NOT NULL, risk_ceiling VARCHAR(16) NOT NULL, expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ, delegation_digest VARCHAR(64) NOT NULL, PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,delegation_digest), {WORKSPACE_FK})"""
    )
    op.execute(
        f"""CREATE TABLE agent_plans ({TENANT}, id UUID NOT NULL, version INTEGER NOT NULL CHECK(version>0), manifest_id UUID NOT NULL, manifest_version INTEGER NOT NULL, plan_json TEXT NOT NULL, plan_digest VARCHAR(64) NOT NULL, status VARCHAR(24) NOT NULL, classification VARCHAR(16) NOT NULL, policy_version INTEGER NOT NULL CHECK(policy_version>0), idempotency_key VARCHAR(128) NOT NULL, created_by_user_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id,version), UNIQUE (organization_id,workspace_id,cell_id,idempotency_key), FOREIGN KEY (organization_id,workspace_id,cell_id,manifest_id,manifest_version) REFERENCES agent_manifest_versions(organization_id,workspace_id,cell_id,manifest_id,version) ON DELETE RESTRICT)"""
    )
    op.execute(
        f"""CREATE TABLE agent_plan_steps ({TENANT}, plan_id UUID NOT NULL, plan_version INTEGER NOT NULL, step_key VARCHAR(128) NOT NULL, tool_id UUID NOT NULL, tool_key VARCHAR(128) NOT NULL, tool_version INTEGER NOT NULL, step_json TEXT NOT NULL, action_digest VARCHAR(64) NOT NULL, status VARCHAR(24) NOT NULL, PRIMARY KEY (organization_id,workspace_id,cell_id,plan_id,plan_version,step_key), FOREIGN KEY (organization_id,workspace_id,cell_id,plan_id,plan_version) REFERENCES agent_plans(organization_id,workspace_id,cell_id,id,version) ON DELETE RESTRICT, FOREIGN KEY (organization_id,workspace_id,cell_id,tool_id,tool_version) REFERENCES agent_tool_versions(organization_id,workspace_id,cell_id,tool_id,version) ON DELETE RESTRICT)"""
    )
    op.execute(
        f"""CREATE TABLE agent_budget_reservations ({TENANT}, id UUID NOT NULL, manifest_id UUID NOT NULL, manifest_version INTEGER NOT NULL, plan_id UUID NOT NULL, plan_version INTEGER NOT NULL, tokens INTEGER NOT NULL CHECK(tokens>=0), cost_micros INTEGER NOT NULL CHECK(cost_micros>=0), tool_calls INTEGER NOT NULL CHECK(tool_calls>=0), seconds INTEGER NOT NULL CHECK(seconds>=0), idempotency_key VARCHAR(128) NOT NULL, released_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,idempotency_key), FOREIGN KEY (organization_id,workspace_id,cell_id,manifest_id,manifest_version) REFERENCES agent_manifest_versions(organization_id,workspace_id,cell_id,manifest_id,version) ON DELETE RESTRICT, FOREIGN KEY (organization_id,workspace_id,cell_id,plan_id,plan_version) REFERENCES agent_plans(organization_id,workspace_id,cell_id,id,version) ON DELETE RESTRICT)"""
    )
    op.execute(
        f"""CREATE TABLE agent_orchestrations ({TENANT}, id UUID NOT NULL, plan_id UUID NOT NULL, plan_version INTEGER NOT NULL, delegation_id UUID NOT NULL, status VARCHAR(24) NOT NULL, current_step_key VARCHAR(128), idempotency_key VARCHAR(128) NOT NULL, version INTEGER NOT NULL CHECK(version>0), cancelled_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,idempotency_key), FOREIGN KEY (organization_id,workspace_id,cell_id,plan_id,plan_version) REFERENCES agent_plans(organization_id,workspace_id,cell_id,id,version) ON DELETE RESTRICT, FOREIGN KEY (organization_id,workspace_id,cell_id,delegation_id) REFERENCES agent_delegations(organization_id,workspace_id,cell_id,id) ON DELETE RESTRICT)"""
    )
    op.execute(
        f"""CREATE TABLE agent_execution_receipts ({TENANT}, id UUID NOT NULL, orchestration_id UUID NOT NULL, step_key VARCHAR(128) NOT NULL, command_receipt_id UUID NOT NULL, action_digest VARCHAR(64) NOT NULL, result_digest VARCHAR(64) NOT NULL, outcome VARCHAR(24) NOT NULL, verified BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,orchestration_id,step_key), FOREIGN KEY (organization_id,workspace_id,cell_id,orchestration_id) REFERENCES agent_orchestrations(organization_id,workspace_id,cell_id,id) ON DELETE RESTRICT)"""
    )
    op.execute(
        f"""CREATE TABLE agent_evaluation_runs ({TENANT}, id UUID NOT NULL, run_key VARCHAR(128) NOT NULL, manifest_id UUID NOT NULL, manifest_version INTEGER NOT NULL, evaluation_set_key VARCHAR(128) NOT NULL, result_digest VARCHAR(64) NOT NULL, passed BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,run_key), FOREIGN KEY (organization_id,workspace_id,cell_id,manifest_id,manifest_version) REFERENCES agent_manifest_versions(organization_id,workspace_id,cell_id,manifest_id,version) ON DELETE RESTRICT)"""
    )
    for table in TABLES:
        secure(table)


def downgrade() -> None:
    union = " + ".join(f"(SELECT count(*) FROM {table})" for table in TABLES)
    op.execute(
        f"""DO $$ BEGIN IF ({union}) > 0 THEN RAISE EXCEPTION 'H3-10 agent platform state requires a reviewed forward fix or export'; END IF; END $$"""
    )
    for table in reversed(TABLES):
        op.drop_table(table)
