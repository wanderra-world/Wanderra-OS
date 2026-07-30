"""Add immutable audit chaining and transactional messaging state.

Revision ID: 0012_h1_audit_messaging
Revises: 0011_h1_envelopes
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_h1_audit_messaging"
down_revision: str | Sequence[str] | None = "0011_h1_envelopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "audit_chain_heads",
    "command_idempotency",
    "aggregate_versions",
    "inbox_events",
    "consumer_sequences",
    "event_quarantine",
)


def _enable_workspace_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table_name}_workspace_isolation ON {table_name}
        USING (
            workspace_id = NULLIF(
                current_setting('atlas.workspace_id', TRUE), ''
            )::UUID
        )
        WITH CHECK (
            workspace_id = NULLIF(
                current_setting('atlas.workspace_id', TRUE), ''
            )::UUID
        )
        """
    )


def _add_audit_columns() -> None:
    for column in (
        sa.Column("decision_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("causation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "classification",
            sa.String(length=32),
            server_default="internal",
            nullable=False,
        ),
        sa.Column("chain_sequence", sa.BigInteger(), nullable=True),
        sa.Column("previous_digest", sa.String(length=64), nullable=True),
        sa.Column("safe_digest", sa.String(length=64), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("partition_key", sa.String(length=7), nullable=True),
    ):
        op.add_column("audit_events", column)


def _add_outbox_columns() -> None:
    for column in (
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("delegation_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("causation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "classification",
            sa.String(length=32),
            server_default="internal",
            nullable=False,
        ),
        sa.Column("schema_major", sa.Integer(), server_default="1", nullable=False),
        sa.Column("schema_minor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("payload_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "quarantined",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("partition_key", sa.String(length=7), nullable=True),
    ):
        op.add_column("outbox_events", column)
    op.execute(
        """
        UPDATE outbox_events
        SET schema_major = schema_version,
            partition_key = to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM')
        """
    )


def _create_messaging_tables() -> None:
    op.create_table(
        "audit_chain_heads",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "last_digest",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "verified_sequence",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_audit_chain_heads_workspace",
        ),
        sa.PrimaryKeyConstraint("workspace_id", name="pk_audit_chain_heads"),
    )
    op.create_table(
        "command_idempotency",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("command_type", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="started", nullable=False),
        sa.Column("outcome_event_id", sa.Uuid(), nullable=True),
        sa.Column("aggregate_version", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('started', 'completed')",
            name="ck_command_idempotency_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_command_idempotency_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "actor_id",
            "command_type",
            "idempotency_key",
            name="pk_command_idempotency",
        ),
    )
    op.create_index(
        "ix_command_idempotency_retention",
        "command_idempotency",
        ["workspace_id", "retention_until"],
    )
    op.create_table(
        "aggregate_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=96), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 0", name="ck_aggregate_versions_version"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_aggregate_versions_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "aggregate_type",
            "aggregate_id",
            name="pk_aggregate_versions",
        ),
    )
    op.create_table(
        "inbox_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("consumer_id", sa.String(length=128), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("schema_major", sa.Integer(), nullable=False),
        sa.Column("schema_minor", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=96), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('processed', 'quarantined')",
            name="ck_inbox_events_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_inbox_events_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "consumer_id",
            "event_id",
            name="pk_inbox_events",
        ),
    )
    op.create_index(
        "ix_inbox_events_retention",
        "inbox_events",
        ["workspace_id", "retention_until"],
    )
    op.create_table(
        "consumer_sequences",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("consumer_id", sa.String(length=128), nullable=False),
        sa.Column("aggregate_type", sa.String(length=96), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_sequence >= 0",
            name="ck_consumer_sequences_last_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_consumer_sequences_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "consumer_id",
            "aggregate_type",
            "aggregate_id",
            name="pk_consumer_sequences",
        ),
    )
    op.create_table(
        "event_quarantine",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("consumer_id", sa.String(length=128), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=96), nullable=False),
        sa.Column("expected_sequence", sa.Integer(), nullable=True),
        sa.Column("observed_sequence", sa.Integer(), nullable=True),
        sa.Column(
            "event_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="quarantined",
            nullable=False,
        ),
        sa.Column(
            "quarantined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replayed_by", sa.Uuid(), nullable=True),
        sa.Column("replay_decision_id", sa.Uuid(), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('quarantined', 'replayed')",
            name="ck_event_quarantine_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_event_quarantine_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_event_quarantine",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "consumer_id",
            "event_id",
            name="uq_event_quarantine_consumer_event",
        ),
    )
    op.create_index(
        "ix_event_quarantine_status",
        "event_quarantine",
        ["workspace_id", "status", "quarantined_at"],
    )


def _create_audit_chain() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE FUNCTION compute_audit_event_digest(
            prior_digest TEXT,
            audit_workspace_id UUID,
            audit_sequence BIGINT,
            audit_id UUID,
            audit_actor_type TEXT,
            audit_actor_id UUID,
            audit_action TEXT,
            audit_target_type TEXT,
            audit_target_id UUID,
            audit_outcome TEXT,
            audit_details JSONB,
            audit_decision_id UUID,
            audit_correlation_id TEXT,
            audit_classification TEXT,
            audit_recorded_at TIMESTAMPTZ
        )
        RETURNS TEXT
        LANGUAGE SQL
        IMMUTABLE
        AS $$
            SELECT encode(
                digest(
                    convert_to(
                        COALESCE(prior_digest, '') || '|' ||
                        jsonb_build_object(
                            'workspace_id', audit_workspace_id,
                            'sequence', audit_sequence,
                            'id', audit_id,
                            'actor_type', audit_actor_type,
                            'actor_id', audit_actor_id,
                            'action', audit_action,
                            'target_type', audit_target_type,
                            'target_id', audit_target_id,
                            'outcome', audit_outcome,
                            'details', audit_details,
                            'decision_id', audit_decision_id,
                            'correlation_id', audit_correlation_id,
                            'classification', audit_classification,
                            'recorded_at', audit_recorded_at
                        )::TEXT,
                        'UTF8'
                    ),
                    'sha256'
                ),
                'hex'
            )
        $$;
        """
    )
    op.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_are_immutable")
    op.execute(
        """
        DO $$
        DECLARE
            item RECORD;
            prior TEXT := '';
            prior_workspace UUID := NULL;
            sequence_number BIGINT := 0;
            computed TEXT;
        BEGIN
            FOR item IN
                SELECT * FROM audit_events
                ORDER BY workspace_id, recorded_at, id
            LOOP
                IF prior_workspace IS DISTINCT FROM item.workspace_id THEN
                    prior := '';
                    sequence_number := 0;
                    prior_workspace := item.workspace_id;
                END IF;
                sequence_number := sequence_number + 1;
                computed := compute_audit_event_digest(
                    prior, item.workspace_id, sequence_number, item.id,
                    item.actor_type, item.actor_id, item.action,
                    item.target_type, item.target_id, item.outcome,
                    item.details, item.decision_id, item.correlation_id,
                    item.classification, item.recorded_at
                );
                UPDATE audit_events
                SET chain_sequence = sequence_number,
                    previous_digest = NULLIF(prior, ''),
                    safe_digest = computed,
                    partition_key = to_char(
                        item.recorded_at AT TIME ZONE 'UTC', 'YYYY-MM'
                    )
                WHERE workspace_id = item.workspace_id AND id = item.id;
                prior := computed;
            END LOOP;
        END
        $$;
        """
    )
    op.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_are_immutable")
    op.execute(
        """
        INSERT INTO audit_chain_heads (
            workspace_id, last_sequence, last_digest
        )
        SELECT DISTINCT ON (workspace_id)
            workspace_id, chain_sequence, safe_digest
        FROM audit_events
        ORDER BY workspace_id, chain_sequence DESC
        """
    )
    op.execute(
        """
        CREATE FUNCTION chain_audit_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            head audit_chain_heads%ROWTYPE;
        BEGIN
            INSERT INTO audit_chain_heads (
                workspace_id, last_sequence, last_digest
            )
            VALUES (NEW.workspace_id, 0, '')
            ON CONFLICT (workspace_id) DO NOTHING;

            SELECT * INTO head
            FROM audit_chain_heads
            WHERE workspace_id = NEW.workspace_id
            FOR UPDATE;

            NEW.chain_sequence := head.last_sequence + 1;
            NEW.previous_digest := NULLIF(head.last_digest, '');
            NEW.partition_key := to_char(
                NEW.recorded_at AT TIME ZONE 'UTC', 'YYYY-MM'
            );
            NEW.safe_digest := compute_audit_event_digest(
                head.last_digest, NEW.workspace_id, NEW.chain_sequence, NEW.id,
                NEW.actor_type, NEW.actor_id, NEW.action, NEW.target_type,
                NEW.target_id, NEW.outcome, NEW.details, NEW.decision_id,
                NEW.correlation_id, NEW.classification, NEW.recorded_at
            );

            UPDATE audit_chain_heads
            SET last_sequence = NEW.chain_sequence,
                last_digest = NEW.safe_digest,
                updated_at = now()
            WHERE workspace_id = NEW.workspace_id;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_chain_insert
        BEFORE INSERT ON audit_events
        FOR EACH ROW EXECUTE FUNCTION chain_audit_event();
        """
    )
    op.execute(
        """
        CREATE FUNCTION verify_audit_chain(checked_workspace_id UUID)
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        AS $$
        DECLARE
            item RECORD;
            prior TEXT := '';
            expected_sequence BIGINT := 0;
            computed TEXT;
        BEGIN
            FOR item IN
                SELECT * FROM audit_events
                WHERE workspace_id = checked_workspace_id
                ORDER BY chain_sequence
            LOOP
                expected_sequence := expected_sequence + 1;
                computed := compute_audit_event_digest(
                    prior, item.workspace_id, expected_sequence, item.id,
                    item.actor_type, item.actor_id, item.action,
                    item.target_type, item.target_id, item.outcome,
                    item.details, item.decision_id, item.correlation_id,
                    item.classification, item.recorded_at
                );
                IF item.chain_sequence <> expected_sequence
                   OR COALESCE(item.previous_digest, '') <> prior
                   OR item.safe_digest <> computed THEN
                    RETURN FALSE;
                END IF;
                prior := computed;
            END LOOP;
            UPDATE audit_chain_heads
            SET verified_sequence = expected_sequence,
                verified_at = now()
            WHERE workspace_id = checked_workspace_id;
            RETURN TRUE;
        END;
        $$;
        """
    )


def upgrade() -> None:
    _add_audit_columns()
    _add_outbox_columns()
    _create_messaging_tables()
    for table_name in TENANT_TABLES:
        _enable_workspace_rls(table_name)
    _create_audit_chain()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM command_idempotency)
               OR EXISTS (SELECT 1 FROM aggregate_versions)
               OR EXISTS (SELECT 1 FROM inbox_events)
               OR EXISTS (SELECT 1 FROM consumer_sequences)
               OR EXISTS (SELECT 1 FROM event_quarantine)
               OR EXISTS (
                    SELECT 1 FROM audit_events
                    WHERE decision_id IS NOT NULL
                       OR correlation_id IS NOT NULL
                       OR causation_id IS NOT NULL
               )
               OR EXISTS (
                    SELECT 1 FROM outbox_events
                    WHERE actor_id IS NOT NULL
                       OR correlation_id IS NOT NULL
                       OR causation_id IS NOT NULL
                       OR idempotency_key IS NOT NULL
                       OR payload_digest IS NOT NULL
               )
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H1-08 with messaging state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    op.execute("DROP FUNCTION verify_audit_chain(UUID)")
    op.execute("DROP TRIGGER audit_events_chain_insert ON audit_events")
    op.execute("DROP FUNCTION chain_audit_event()")
    op.execute(
        "DROP FUNCTION compute_audit_event_digest("
        "TEXT, UUID, BIGINT, UUID, TEXT, UUID, TEXT, TEXT, UUID, TEXT, "
        "JSONB, UUID, TEXT, TEXT, TIMESTAMPTZ)"
    )
    for table_name in reversed(TENANT_TABLES):
        op.drop_table(table_name)
    for column_name in (
        "partition_key",
        "retention_until",
        "quarantined",
        "attempt_count",
        "available_at",
        "payload_digest",
        "idempotency_key",
        "schema_minor",
        "schema_major",
        "classification",
        "causation_id",
        "correlation_id",
        "delegation_id",
        "actor_id",
    ):
        op.drop_column("outbox_events", column_name)
    op.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_are_immutable")
    for column_name in (
        "partition_key",
        "retention_until",
        "safe_digest",
        "previous_digest",
        "chain_sequence",
        "classification",
        "causation_id",
        "correlation_id",
        "decision_id",
    ):
        op.drop_column("audit_events", column_name)
    op.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_are_immutable")
