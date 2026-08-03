"""Add provider-neutral H3-07 canonical Task Manager.

Revision ID: 0028_h3_task_manager
Revises: 0027_h3_search_context
"""

# ruff: noqa: E501
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0028_h3_task_manager"
down_revision = "0027_h3_search_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "tasks",
    "task_participants",
    "task_dependencies",
    "task_comments",
    "task_completion_evidence",
    "task_external_references",
    "task_reminders",
)


def tenant() -> tuple[sa.Column, ...]:
    return (
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("cell_id", sa.Uuid(), nullable=False),
    )


def workspace_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "organization_id", "cell_id"],
        ["workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id"],
        ondelete="RESTRICT",
        name=name,
    )


def task_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "workspace_id", "cell_id", column],
        ["tasks.organization_id", "tasks.workspace_id", "tasks.cell_id", "tasks.id"],
        ondelete="RESTRICT",
        name=name,
    )


def secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""CREATE POLICY {table}_workspace_isolation ON {table} USING (workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID AND organization_id = NULLIF(current_setting('atlas.organization_id', TRUE), '')::UUID AND cell_id = NULLIF(current_setting('atlas.cell_id', TRUE), '')::UUID) WITH CHECK (workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID AND organization_id = NULLIF(current_setting('atlas.organization_id', TRUE), '')::UUID AND cell_id = NULLIF(current_setting('atlas.cell_id', TRUE), '')::UUID)"""
    )
    op.execute(
        f"CREATE TRIGGER {table}_workspace_writable BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()"
    )


def upgrade() -> None:
    op.create_table(
        "tasks",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(24), server_default="open", nullable=False),
        sa.Column("priority", sa.String(16), server_default="normal", nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("timezone", sa.String(64)),
        sa.Column("recurrence_reference", sa.String(128)),
        sa.Column("source_resource_id", sa.Uuid()),
        sa.Column(
            "completion_evidence_required", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
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
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_tasks"
        ),
        sa.UniqueConstraint(
            "organization_id", "workspace_id", "cell_id", "resource_id", name="uq_tasks_resource"
        ),
        workspace_fk("fk_tasks_workspace"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "resource_id"],
            [
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ],
            ondelete="RESTRICT",
            name="fk_tasks_resource",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "source_resource_id"],
            [
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ],
            ondelete="RESTRICT",
            name="fk_tasks_source",
        ),
        sa.CheckConstraint(
            "status IN ('open','in_progress','blocked','completed','cancelled','deleted')",
            name="ck_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low','normal','high','urgent')", name="ck_tasks_priority"
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_tasks_classification",
        ),
        sa.CheckConstraint("version > 0 AND policy_version > 0", name="ck_tasks_versions"),
    )
    op.create_index("ix_tasks_workspace_status_due", "tasks", ["workspace_id", "status", "due_at"])
    op.create_table(
        "task_participants",
        *tenant(),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=False),
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
            "task_id",
            "user_id",
            "kind",
            name="pk_task_participants",
        ),
        task_fk("task_id", "fk_task_participants_task"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_memberships.workspace_id", "workspace_memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_task_participants_membership",
        ),
        sa.CheckConstraint("kind IN ('assignee','watcher')", name="ck_task_participants_kind"),
    )
    op.create_table(
        "task_dependencies",
        *tenant(),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_task_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
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
            "task_id",
            "depends_on_task_id",
            name="pk_task_dependencies",
        ),
        task_fk("task_id", "fk_task_dependencies_task"),
        task_fk("depends_on_task_id", "fk_task_dependencies_target"),
        sa.CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dependencies_distinct"),
    )
    op.create_table(
        "task_comments",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_task_comments"
        ),
        task_fk("task_id", "fk_task_comments_task"),
    )
    op.create_table(
        "task_completion_evidence",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_resource_id", sa.Uuid()),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("supersedes_evidence_id", sa.Uuid()),
        sa.Column("recorded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_task_completion_evidence"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "task_id",
            "evidence_digest",
            name="uq_task_evidence_digest",
        ),
        task_fk("task_id", "fk_task_evidence_task"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "evidence_resource_id"],
            [
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ],
            ondelete="RESTRICT",
            name="fk_task_evidence_resource",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "supersedes_evidence_id"],
            [
                "task_completion_evidence.organization_id",
                "task_completion_evidence.workspace_id",
                "task_completion_evidence.cell_id",
                "task_completion_evidence.id",
            ],
            ondelete="RESTRICT",
            name="fk_task_evidence_supersedes",
        ),
    )
    op.create_table(
        "task_external_references",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("authority", sa.String(96), nullable=False),
        sa.Column("external_id", sa.String(256), nullable=False),
        sa.Column("external_version", sa.String(128)),
        sa.Column("linked_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_task_external_references"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "authority",
            "external_id",
            name="uq_task_external_authority",
        ),
        task_fk("task_id", "fk_task_external_task"),
    )
    op.create_table(
        "task_reminders",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("identity_key", sa.String(128), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="scheduled", nullable=False),
        sa.Column("job_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_task_reminders"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "identity_key",
            name="uq_task_reminder_identity",
        ),
        task_fk("task_id", "fk_task_reminders_task"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "job_id"],
            [
                "job_instances.organization_id",
                "job_instances.workspace_id",
                "job_instances.cell_id",
                "job_instances.id",
            ],
            ondelete="RESTRICT",
            name="fk_task_reminders_job",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','cancelled','dispatched')", name="ck_task_reminders_status"
        ),
    )
    for table in TABLES:
        secure(table)
    op.execute("""
        CREATE FUNCTION prevent_task_evidence_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'task completion evidence is immutable';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER task_completion_evidence_immutable
        BEFORE UPDATE OR DELETE ON task_completion_evidence
        FOR EACH ROW EXECUTE FUNCTION prevent_task_evidence_mutation()
    """)


def downgrade() -> None:
    connection = op.get_bind()
    populated = [
        table
        for table in TABLES
        if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")).scalar()
    ]
    if populated:
        raise RuntimeError("H3-07 task state exists; use a reviewed forward fix or export")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION prevent_task_evidence_mutation()")
