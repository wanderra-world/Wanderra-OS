"""Add provider-neutral H3-08 workflow and approval state.

Revision ID: 0029_h3_workflow_approval
Revises: 0028_h3_task_manager
"""

# ruff: noqa: E501
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0029_h3_workflow_approval"
down_revision = "0028_h3_task_manager"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
TABLES = (
    "workflow_definitions",
    "workflow_definition_versions",
    "workflow_instances",
    "workflow_tokens",
    "workflow_waits",
    "workflow_approvals",
    "workflow_approval_decisions",
    "workflow_receipts",
)


def tenant() -> tuple[sa.Column, ...]:
    return (
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("cell_id", sa.Uuid(), nullable=False),
    )


def workspace(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "organization_id", "cell_id"],
        ["workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id"],
        ondelete="RESTRICT",
        name=name,
    )


def secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_workspace_isolation ON {table} USING (workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID AND organization_id = NULLIF(current_setting('atlas.organization_id', TRUE), '')::UUID AND cell_id = NULLIF(current_setting('atlas.cell_id', TRUE), '')::UUID) WITH CHECK (workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID AND organization_id = NULLIF(current_setting('atlas.organization_id', TRUE), '')::UUID AND cell_id = NULLIF(current_setting('atlas.cell_id', TRUE), '')::UUID)"
    )
    op.execute(
        f"CREATE TRIGGER {table}_workspace_writable BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()"
    )


def instance_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "workspace_id", "cell_id", "instance_id"],
        [
            "workflow_instances.organization_id",
            "workflow_instances.workspace_id",
            "workflow_instances.cell_id",
            "workflow_instances.id",
        ],
        ondelete="RESTRICT",
        name=name,
    )


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_workflow_definitions"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "name",
            name="uq_workflow_definitions_name",
        ),
        workspace("fk_workflow_definitions_workspace"),
    )
    op.create_table(
        "workflow_definition_versions",
        *tenant(),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("schema_digest", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "definition_id",
            "version",
            name="pk_workflow_definition_versions",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "definition_id"],
            [
                "workflow_definitions.organization_id",
                "workflow_definitions.workspace_id",
                "workflow_definitions.cell_id",
                "workflow_definitions.id",
            ],
            ondelete="RESTRICT",
            name="fk_workflow_versions_definition",
        ),
        sa.CheckConstraint(
            "version > 0 AND policy_version > 0", name="ck_workflow_version_positive"
        ),
    )
    op.create_table(
        "workflow_instances",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_step_key", sa.String(128)),
        sa.Column("state_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("started_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_workflow_instances"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "idempotency_key",
            name="uq_workflow_instance_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "definition_id", "definition_version"],
            [
                "workflow_definition_versions.organization_id",
                "workflow_definition_versions.workspace_id",
                "workflow_definition_versions.cell_id",
                "workflow_definition_versions.definition_id",
                "workflow_definition_versions.version",
            ],
            ondelete="RESTRICT",
            name="fk_workflow_instances_version",
        ),
        sa.CheckConstraint("version > 0", name="ck_workflow_instance_version"),
    )
    op.create_table(
        "workflow_tokens",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(128), nullable=False),
        sa.Column("transition_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("output_digest", sa.String(64)),
        sa.Column("job_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_workflow_tokens"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "instance_id",
            "transition_key",
            name="uq_workflow_transition",
        ),
        instance_fk("fk_workflow_tokens_instance"),
    )
    op.create_table(
        "workflow_waits",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(128), nullable=False),
        sa.Column("resume_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), server_default="waiting", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_workflow_waits"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "resume_key",
            name="uq_workflow_wait_resume",
        ),
        instance_fk("fk_workflow_waits_instance"),
    )
    op.create_table(
        "workflow_approvals",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(128), nullable=False),
        sa.Column("action_digest", sa.String(64), nullable=False),
        sa.Column("risk", sa.String(16), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_workflow_approvals"
        ),
        instance_fk("fk_workflow_approvals_instance"),
    )
    op.create_table(
        "workflow_approval_decisions",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("action_digest", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "id",
            name="pk_workflow_approval_decisions",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "approval_id",
            "approver_id",
            name="uq_workflow_approval_approver",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "approval_id"],
            [
                "workflow_approvals.organization_id",
                "workflow_approvals.workspace_id",
                "workflow_approvals.cell_id",
                "workflow_approvals.id",
            ],
            ondelete="RESTRICT",
            name="fk_workflow_decisions_approval",
        ),
    )
    op.create_table(
        "workflow_receipts",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("transition_key", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("action_digest", sa.String(64), nullable=False),
        sa.Column("result_digest", sa.String(64)),
        sa.Column("compensation", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("uncertain", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_workflow_receipts"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "instance_id",
            "transition_key",
            name="uq_workflow_receipt_transition",
        ),
        instance_fk("fk_workflow_receipts_instance"),
    )
    for table in TABLES:
        secure(table)
    op.execute(
        """
        CREATE FUNCTION protect_h3_workflow_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'H3-08 accepted workflow evidence is immutable';
        END; $$
        """
    )
    for table in ("workflow_approval_decisions", "workflow_receipts"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_h3_workflow_evidence()"
        )
    op.execute(
        """
        CREATE FUNCTION protect_active_workflow_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.activated_at IS NOT NULL THEN
            RAISE EXCEPTION 'active workflow definition versions are immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER workflow_definition_versions_immutable "
        "BEFORE UPDATE OR DELETE ON workflow_definition_versions FOR EACH ROW "
        "EXECUTE FUNCTION protect_active_workflow_version()"
    )


def downgrade() -> None:
    connection = op.get_bind()
    populated = [
        table
        for table in TABLES
        if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")).scalar()
    ]
    if populated:
        raise RuntimeError(
            "H3-08 workflow evidence exists; destructive downgrade requires a reviewed forward fix or export"
        )
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION protect_active_workflow_version()")
    op.execute("DROP FUNCTION protect_h3_workflow_evidence()")
