"""Add provider-neutral H3-11 observation and operator evidence.

Revision ID: 0032_h3_platform_hardening
Revises: 0031_h3_agent_platform
"""

# ruff: noqa: E501
from collections.abc import Sequence

from alembic import op

revision = "0032_h3_platform_hardening"
down_revision = "0031_h3_agent_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "platform_telemetry_records",
    "platform_evaluation_runs",
    "platform_operator_actions",
    "platform_recovery_drills",
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
        f"""CREATE TABLE platform_telemetry_records ({TENANT}, id UUID NOT NULL, record_key VARCHAR(128) NOT NULL, schema_version INTEGER NOT NULL CHECK(schema_version>0), signal_key VARCHAR(128) NOT NULL, correlation_id VARCHAR(128) NOT NULL, classification VARCHAR(16) NOT NULL, value DOUBLE PRECISION NOT NULL, unit VARCHAR(32) NOT NULL, labels_json TEXT NOT NULL, evidence_digest VARCHAR(64) NOT NULL, occurred_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,record_key), {WORKSPACE_FK})"""
    )
    op.execute(
        f"""CREATE TABLE platform_evaluation_runs ({TENANT}, id UUID NOT NULL, run_key VARCHAR(128) NOT NULL, dataset_key VARCHAR(128) NOT NULL, dataset_version INTEGER NOT NULL CHECK(dataset_version>0), commit_sha VARCHAR(40) NOT NULL, result_digest VARCHAR(64) NOT NULL, passed BOOLEAN NOT NULL, critical_findings INTEGER NOT NULL CHECK(critical_findings>=0), high_findings INTEGER NOT NULL CHECK(high_findings>=0), measured_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,run_key), {WORKSPACE_FK})"""
    )
    op.execute(
        f"""CREATE TABLE platform_operator_actions ({TENANT}, id UUID NOT NULL, actor_id UUID NOT NULL, action VARCHAR(24) NOT NULL, scope_type VARCHAR(24) NOT NULL, scope_reference VARCHAR(128) NOT NULL, expected_version INTEGER NOT NULL DEFAULT 0 CHECK(expected_version>=0), reason VARCHAR(256) NOT NULL, idempotency_key VARCHAR(128) NOT NULL, evidence_digest VARCHAR(64) NOT NULL, occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,idempotency_key), {WORKSPACE_FK})"""
    )
    op.execute(
        f"""CREATE TABLE platform_recovery_drills ({TENANT}, id UUID NOT NULL, drill_key VARCHAR(128) NOT NULL, drill_type VARCHAR(24) NOT NULL, artifact_digest VARCHAR(64) NOT NULL, restored_digest VARCHAR(64) NOT NULL, rpo_seconds INTEGER NOT NULL CHECK(rpo_seconds>=0), rto_seconds INTEGER NOT NULL CHECK(rto_seconds>=0), passed BOOLEAN NOT NULL, performed_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,drill_key), {WORKSPACE_FK})"""
    )
    for table in TABLES:
        secure(table)


def downgrade() -> None:
    union = " + ".join(f"(SELECT count(*) FROM {table})" for table in TABLES)
    op.execute(
        f"""DO $$ BEGIN IF ({union}) > 0 THEN RAISE EXCEPTION 'H3-11 platform hardening evidence requires a reviewed forward fix or export'; END IF; END $$"""
    )
    for table in reversed(TABLES):
        op.drop_table(table)
