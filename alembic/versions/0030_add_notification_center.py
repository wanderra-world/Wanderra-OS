"""Add provider-neutral H3-09 Notification Center state.

Revision ID: 0030_h3_notification_center
Revises: 0029_h3_workflow_approval
"""

# ruff: noqa: E501

from collections.abc import Sequence

from alembic import op

revision = "0030_h3_notification_center"
down_revision = "0029_h3_workflow_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "notification_templates", "notification_template_versions", "notification_preferences",
    "notification_intents", "notification_digests", "notification_attempts",
    "notification_receipts", "notification_inbox_entries",
)
TENANT = "organization_id UUID NOT NULL, workspace_id UUID NOT NULL, cell_id UUID NOT NULL"
WORKSPACE_FK = "FOREIGN KEY (workspace_id,organization_id,cell_id) REFERENCES workspaces(workspace_id,organization_id,cell_id) ON DELETE RESTRICT"


def secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    predicate = "workspace_id=NULLIF(current_setting('atlas.workspace_id',TRUE),'')::UUID AND organization_id=NULLIF(current_setting('atlas.organization_id',TRUE),'')::UUID AND cell_id=NULLIF(current_setting('atlas.cell_id',TRUE),'')::UUID"
    op.execute(f"CREATE POLICY {table}_workspace_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})")
    op.execute(f"CREATE TRIGGER {table}_workspace_writable BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()")


def upgrade() -> None:
    op.execute(f"""CREATE TABLE notification_templates ({TENANT}, id UUID NOT NULL, template_key VARCHAR(128) NOT NULL, created_by_user_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,template_key), {WORKSPACE_FK})""")
    op.execute(f"""CREATE TABLE notification_template_versions ({TENANT}, template_id UUID NOT NULL, version INTEGER NOT NULL CHECK(version>0), subject VARCHAR(512) NOT NULL, body TEXT NOT NULL, allowed_variables_json TEXT NOT NULL, maximum_classification VARCHAR(16) NOT NULL, template_digest VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,template_id,version), FOREIGN KEY (organization_id,workspace_id,cell_id,template_id) REFERENCES notification_templates(organization_id,workspace_id,cell_id,id) ON DELETE RESTRICT)""")
    op.execute(f"""CREATE TABLE notification_preferences ({TENANT}, user_id UUID NOT NULL, channel VARCHAR(128) NOT NULL, enabled BOOLEAN NOT NULL, maximum_classification VARCHAR(16) NOT NULL, timezone VARCHAR(64) NOT NULL, quiet_start VARCHAR(8), quiet_end VARCHAR(8), digest_enabled BOOLEAN NOT NULL DEFAULT false, policy_version INTEGER NOT NULL CHECK(policy_version>0), PRIMARY KEY (organization_id,workspace_id,cell_id,user_id,channel), {WORKSPACE_FK})""")
    op.execute(f"""CREATE TABLE notification_intents ({TENANT}, id UUID NOT NULL, intent_key VARCHAR(256) NOT NULL, deduplication_key VARCHAR(256) NOT NULL, intent_digest VARCHAR(64) NOT NULL, source_type VARCHAR(64) NOT NULL, source_id UUID NOT NULL, recipient_user_id UUID NOT NULL, destination_reference VARCHAR(256) NOT NULL, template_key VARCHAR(128) NOT NULL, template_version INTEGER NOT NULL CHECK(template_version>0), classification VARCHAR(16) NOT NULL, purpose VARCHAR(64) NOT NULL, policy_version INTEGER NOT NULL CHECK(policy_version>0), variables_json TEXT NOT NULL, status VARCHAR(24) NOT NULL, deliver_after TIMESTAMPTZ NOT NULL, cancelled_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,intent_key), UNIQUE (organization_id,workspace_id,cell_id,deduplication_key), {WORKSPACE_FK})""")
    op.execute(f"""CREATE TABLE notification_digests ({TENANT}, id UUID NOT NULL, digest_key VARCHAR(256) NOT NULL, recipient_user_id UUID NOT NULL, channel VARCHAR(128) NOT NULL, window_ends_at TIMESTAMPTZ NOT NULL, status VARCHAR(24) NOT NULL, PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,digest_key), {WORKSPACE_FK})""")
    op.execute(f"""CREATE TABLE notification_attempts ({TENANT}, id UUID NOT NULL, intent_id UUID NOT NULL, attempt_number INTEGER NOT NULL CHECK(attempt_number>0), channel VARCHAR(128) NOT NULL, job_id UUID, status VARCHAR(24) NOT NULL, retry_category VARCHAR(24), rendered_digest VARCHAR(64) NOT NULL, started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ, PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,intent_id,attempt_number), FOREIGN KEY (organization_id,workspace_id,cell_id,intent_id) REFERENCES notification_intents(organization_id,workspace_id,cell_id,id) ON DELETE RESTRICT)""")
    op.execute(f"""CREATE TABLE notification_receipts ({TENANT}, id UUID NOT NULL, attempt_id UUID NOT NULL, outcome VARCHAR(24) NOT NULL, receipt_reference_digest VARCHAR(64), verified BOOLEAN NOT NULL, received_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,attempt_id), FOREIGN KEY (organization_id,workspace_id,cell_id,attempt_id) REFERENCES notification_attempts(organization_id,workspace_id,cell_id,id) ON DELETE RESTRICT)""")
    op.execute(f"""CREATE TABLE notification_inbox_entries ({TENANT}, id UUID NOT NULL, intent_id UUID NOT NULL, recipient_user_id UUID NOT NULL, subject VARCHAR(512) NOT NULL, body TEXT NOT NULL, classification VARCHAR(16) NOT NULL, read_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (organization_id,workspace_id,cell_id,id), UNIQUE (organization_id,workspace_id,cell_id,intent_id), FOREIGN KEY (organization_id,workspace_id,cell_id,intent_id) REFERENCES notification_intents(organization_id,workspace_id,cell_id,id) ON DELETE RESTRICT)""")
    for table in TABLES:
        secure(table)


def downgrade() -> None:
    union = " + ".join(f"(SELECT count(*) FROM {table})" for table in TABLES)
    op.execute(f"""DO $$ BEGIN IF ({union}) > 0 THEN RAISE EXCEPTION 'H3-09 notification state requires a reviewed forward fix or export'; END IF; END $$""")
    for table in reversed(TABLES):
        op.drop_table(table)
