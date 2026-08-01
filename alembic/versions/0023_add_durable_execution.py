"""Add the H3-02 durable execution and scheduler substrate.

Revision ID: 0023_h3_durable_execution
Revises: 0022_h3_resource_graph
"""

# ruff: noqa: E501 -- PostgreSQL policy and rollback bodies remain readable.

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023_h3_durable_execution"
down_revision = "0022_h3_resource_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "job_definitions",
    "job_instances",
    "job_attempts",
    "job_dead_letters",
    "job_schedules",
    "job_operator_controls",
)


def _tenant_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("cell_id", sa.Uuid(), nullable=False),
    )


def _workspace_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "organization_id", "cell_id"],
        ["workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id"],
        ondelete="RESTRICT",
        name=name,
    )


def _definition_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "workspace_id", "cell_id", "definition_id"],
        [
            "job_definitions.organization_id",
            "job_definitions.workspace_id",
            "job_definitions.cell_id",
            "job_definitions.id",
        ],
        ondelete="RESTRICT",
        name=name,
    )


def _job_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "workspace_id", "cell_id", "job_id"],
        [
            "job_instances.organization_id",
            "job_instances.workspace_id",
            "job_instances.cell_id",
            "job_instances.id",
        ],
        ondelete="RESTRICT",
        name=name,
    )


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {table}_workspace_isolation ON {table}
        USING (
          workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
          AND organization_id = NULLIF(current_setting('atlas.organization_id', TRUE), '')::UUID
          AND cell_id = NULLIF(current_setting('atlas.cell_id', TRUE), '')::UUID
        )
        WITH CHECK (
          workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
          AND organization_id = NULLIF(current_setting('atlas.organization_id', TRUE), '')::UUID
          AND cell_id = NULLIF(current_setting('atlas.cell_id', TRUE), '')::UUID
        )
        """)
    op.execute(f"""
        CREATE TRIGGER {table}_workspace_writable
        BEFORE INSERT OR UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()
        """)


def upgrade() -> None:
    op.create_table(
        "job_definitions",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("definition_key", sa.String(96), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("handler_key", sa.String(128), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("retry_delays", postgresql.JSONB(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), server_default="20", nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default="120", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
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
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_job_definitions"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "definition_key",
            "definition_version",
            name="uq_job_definitions_key_version",
        ),
        sa.CheckConstraint("definition_version > 0", name="ck_job_definitions_version"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 5", name="ck_job_definitions_attempts"),
        sa.CheckConstraint(
            "max_concurrency BETWEEN 1 AND 20", name="ck_job_definitions_concurrency"
        ),
        sa.CheckConstraint(
            "rate_limit_per_minute BETWEEN 1 AND 120", name="ck_job_definitions_rate"
        ),
        sa.CheckConstraint(
            "status IN ('active','paused','retired')", name="ck_job_definitions_status"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(retry_delays) = 'array'",
            name="ck_job_definitions_retry_delays",
        ),
        _workspace_fk("fk_job_definitions_workspace"),
    )
    op.create_index(
        "ix_job_definitions_workspace_status", "job_definitions", ["workspace_id", "status"]
    )

    op.create_table(
        "job_instances",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("command_type", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True)),
        sa.Column("cancellation_reason", sa.String(256)),
        sa.Column("replay_of_job_id", sa.Uuid()),
        sa.Column("causation_id", sa.Uuid()),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
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
        sa.Column("result_digest", sa.String(64)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_job_instances"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "definition_id",
            "idempotency_key",
            name="uq_job_instances_idempotency",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','cancelled','dead_lettered','expired')",
            name="ck_job_instances_status",
        ),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 5", name="ck_job_instances_attempt_count"),
        sa.CheckConstraint("state_version > 0", name="ck_job_instances_state_version"),
        sa.CheckConstraint("deadline > available_at", name="ck_job_instances_deadline"),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_job_instances_classification",
        ),
        _workspace_fk("fk_job_instances_workspace"),
        _definition_fk("fk_job_instances_definition"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "resource_id"],
            [
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ],
            ondelete="RESTRICT",
            name="fk_job_instances_resource",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "replay_of_job_id"],
            [
                "job_instances.organization_id",
                "job_instances.workspace_id",
                "job_instances.cell_id",
                "job_instances.id",
            ],
            ondelete="RESTRICT",
            name="fk_job_instances_replay_source",
        ),
    )
    op.create_index(
        "ix_job_instances_claim",
        "job_instances",
        ["workspace_id", "status", "available_at", "created_at"],
    )
    op.create_index("ix_job_instances_lease", "job_instances", ["workspace_id", "lease_expires_at"])

    op.create_table(
        "job_attempts",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), server_default="running", nullable=False),
        sa.Column("failure_category", sa.String(32)),
        sa.Column("error_code", sa.String(96)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_job_attempts"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "job_id",
            "attempt_number",
            name="uq_job_attempts_number",
        ),
        sa.CheckConstraint("attempt_number BETWEEN 1 AND 5", name="ck_job_attempts_number"),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','abandoned','cancelled')",
            name="ck_job_attempts_status",
        ),
        _job_fk("fk_job_attempts_job"),
    )
    op.create_index(
        "ix_job_attempts_job", "job_attempts", ["workspace_id", "job_id", "attempt_number"]
    )

    op.create_table(
        "job_dead_letters",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("failure_category", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(96), nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replayed_at", sa.DateTime(timezone=True)),
        sa.Column("replayed_by_user_id", sa.Uuid()),
        sa.Column("replay_job_id", sa.Uuid()),
        sa.Column("replay_reason", sa.String(256)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_job_dead_letters"
        ),
        sa.UniqueConstraint(
            "organization_id", "workspace_id", "cell_id", "job_id", name="uq_job_dead_letters_job"
        ),
        sa.CheckConstraint("status IN ('open','replayed')", name="ck_job_dead_letters_status"),
        _job_fk("fk_job_dead_letters_job"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "replay_job_id"],
            [
                "job_instances.organization_id",
                "job_instances.workspace_id",
                "job_instances.cell_id",
                "job_instances.id",
            ],
            ondelete="RESTRICT",
            name="fk_job_dead_letters_replay_job",
        ),
    )
    op.create_index(
        "ix_job_dead_letters_status", "job_dead_letters", ["workspace_id", "status", "created_at"]
    )

    op.create_table(
        "job_schedules",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_kind", sa.String(24), nullable=False),
        sa.Column("misfire_policy", sa.String(16), nullable=False),
        sa.Column("first_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_seconds", sa.Integer()),
        sa.Column("timezone", sa.String(64)),
        sa.Column("local_hour", sa.Integer()),
        sa.Column("local_minute", sa.Integer()),
        sa.Column("local_time_policy", sa.String(16)),
        sa.Column("command_type", sa.String(128), nullable=False),
        sa.Column("command_payload", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_prefix", sa.String(96), nullable=False),
        sa.Column("job_deadline_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
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
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_job_schedules"
        ),
        sa.CheckConstraint(
            "schedule_kind IN ('once','interval','daily_local')", name="ck_job_schedules_kind"
        ),
        sa.CheckConstraint(
            "misfire_policy IN ('skip','fire_once','catch_up')", name="ck_job_schedules_misfire"
        ),
        sa.CheckConstraint(
            "status IN ('active','paused','completed')", name="ck_job_schedules_status"
        ),
        _workspace_fk("fk_job_schedules_workspace"),
        _definition_fk("fk_job_schedules_definition"),
    )
    op.create_index(
        "ix_job_schedules_due", "job_schedules", ["workspace_id", "status", "next_due_at"]
    )

    op.create_table(
        "job_operator_controls",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_reference", sa.String(128), nullable=False),
        sa.Column("paused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("changed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_job_operator_controls"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "scope_type",
            "scope_reference",
            name="uq_job_operator_controls_scope",
        ),
        sa.CheckConstraint(
            "scope_type IN ('workspace','definition')", name="ck_job_operator_controls_scope"
        ),
        sa.CheckConstraint("state_version > 0", name="ck_job_operator_controls_version"),
        _workspace_fk("fk_job_operator_controls_workspace"),
    )

    for table in TABLES:
        _rls(table)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM job_instances LIMIT 1)
             OR EXISTS (SELECT 1 FROM job_attempts LIMIT 1)
             OR EXISTS (SELECT 1 FROM job_dead_letters LIMIT 1)
             OR EXISTS (SELECT 1 FROM job_schedules LIMIT 1)
             OR EXISTS (SELECT 1 FROM audit_events WHERE target_type IN ('job','job_definition','job_schedule','job_control') LIMIT 1)
             OR EXISTS (SELECT 1 FROM outbox_events WHERE aggregate_type IN ('job','job_definition','job_schedule','job_control') LIMIT 1)
          THEN
            RAISE EXCEPTION 'H3-02 durable execution state requires a reviewed forward fix or export before downgrade';
          END IF;
        END $$;
        """)
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_workspace_writable ON {table}")
        op.drop_table(table)
