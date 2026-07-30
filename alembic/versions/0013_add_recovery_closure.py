"""Add H1 recovery evidence and workspace closure controls.

Revision ID: 0013_h1_recovery_closure
Revises: 0012_h1_audit_messaging
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_h1_recovery_closure"
down_revision: str | Sequence[str] | None = "0012_h1_audit_messaging"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTROL_TABLES = (
    "workspace_data_governance",
    "workspace_exports",
    "workspace_closures",
    "workspace_recovery_evidence",
)
WRITE_GUARDED_TABLES = (
    "identity_sessions",
    "identity_lifecycle_tokens",
    "security_notifications",
    "workspace_memberships",
    "encrypted_envelopes",
    "outbox_events",
    "command_idempotency",
    "aggregate_versions",
    "inbox_events",
    "consumer_sequences",
    "event_quarantine",
    "workspace_data_governance",
    "workspace_exports",
)


def _enable_rls(table_name: str) -> None:
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


def _create_tables() -> None:
    op.create_table(
        "workspace_data_governance",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "legal_hold",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("legal_hold_reason", sa.Text(), nullable=True),
        sa.Column(
            "minimum_retention_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "policy_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
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
            name="fk_workspace_data_governance_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            name="pk_workspace_data_governance",
        ),
    )
    op.create_table(
        "workspace_exports",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("manifest_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_reconciliation_required",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_workspace_exports_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_workspace_exports",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_workspace_exports_idempotency",
        ),
    )
    op.create_index(
        "ix_workspace_exports_created",
        "workspace_exports",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "workspace_closures",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("initiated_by", sa.Uuid(), nullable=False),
        sa.Column("authorization_decision_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("blocked_reason", sa.String(length=96), nullable=True),
        sa.Column(
            "before_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "after_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "provider_reconciliation_required",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column("receipt_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('writes_frozen', 'retention_blocked', 'erasing', "
            "'closed', 'failed')",
            name="ck_workspace_closures_state",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_workspace_closures_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_workspace_closures",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_workspace_closures_idempotency",
        ),
    )
    op.create_index(
        "ix_workspace_closures_state",
        "workspace_closures",
        ["workspace_id", "state"],
    )
    op.create_table(
        "workspace_recovery_evidence",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("backup_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("isolated_target", sa.String(length=255), nullable=True),
        sa.Column(
            "source_snapshot_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("recovery_point_seconds", sa.Integer(), nullable=True),
        sa.Column("recovery_time_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "counts_verified",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "digests_verified",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "key_access_verified",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.Column("evidence_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation IN ('backup', 'restore', 'key_recovery')",
            name="ck_workspace_recovery_operation",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_workspace_recovery_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_workspace_recovery_evidence_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "backup_id",
            "operation",
            name="pk_workspace_recovery_evidence",
        ),
    )
    op.create_index(
        "ix_workspace_recovery_recorded",
        "workspace_recovery_evidence",
        ["workspace_id", "recorded_at"],
    )


def _create_write_freeze() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_workspace_write_state()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            checked_workspace_id UUID;
            workspace_state TEXT;
        BEGIN
            IF current_setting('atlas.closure_operation', TRUE) = 'true' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            checked_workspace_id := COALESCE(NEW.workspace_id, OLD.workspace_id);
            SELECT status INTO workspace_state
            FROM workspaces WHERE workspace_id = checked_workspace_id;
            IF workspace_state IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'workspace H1 writes are frozen';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )
    for table_name in WRITE_GUARDED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_workspace_writable
            BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()
            """
        )
    op.execute(
        """
        CREATE FUNCTION prevent_recovery_evidence_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND TG_TABLE_NAME = 'workspace_closures'
               AND OLD.state <> 'closed'
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'recovery evidence is immutable';
        END;
        $$;
        """
    )
    for table_name in (
        "workspace_exports",
        "workspace_recovery_evidence",
        "workspace_closures",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_recovery_evidence_mutation()
            """
        )


def _allow_closed_workspace_without_owner() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_workspace_membership_ownership()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            checked_workspace_id UUID;
            checked_organization_id UUID;
            checked_organization_type TEXT;
            checked_workspace_status TEXT;
            active_member_count INTEGER;
            active_owner_count INTEGER;
            personal_member_user_id UUID;
            organization_owner_user_id UUID;
        BEGIN
            checked_workspace_id := COALESCE(NEW.workspace_id, OLD.workspace_id);
            SELECT organization_id, status
              INTO checked_organization_id, checked_workspace_status
              FROM workspaces
             WHERE workspace_id = checked_workspace_id;
            IF checked_organization_id IS NULL
               OR checked_workspace_status IN ('closing', 'closed')
            THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            SELECT organization_type
              INTO checked_organization_type
              FROM organizations
             WHERE id = checked_organization_id;
            SELECT
                count(*) FILTER (WHERE status = 'active'),
                count(*) FILTER (
                    WHERE status = 'active' AND role_key = 'workspace_owner'
                ),
                (array_agg(user_id ORDER BY user_id)
                    FILTER (WHERE status = 'active'))[1]
              INTO active_member_count, active_owner_count, personal_member_user_id
              FROM workspace_memberships
             WHERE workspace_id = checked_workspace_id;
            IF active_owner_count < 1 THEN
                RAISE EXCEPTION
                    'workspace must retain at least one active workspace owner';
            END IF;
            IF checked_organization_type = 'personal' THEN
                SELECT user_id
                  INTO organization_owner_user_id
                  FROM organization_memberships
                 WHERE organization_id = checked_organization_id
                   AND role = 'owner'
                   AND status = 'active';
                IF active_member_count <> 1
                   OR personal_member_user_id IS DISTINCT FROM organization_owner_user_id
                THEN
                    RAISE EXCEPTION
                        'personal workspace must have exactly its organization owner';
                END IF;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )


def upgrade() -> None:
    _create_tables()
    for table_name in CONTROL_TABLES:
        _enable_rls(table_name)
    _create_write_freeze()
    _allow_closed_workspace_without_owner()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM workspace_data_governance)
               OR EXISTS (SELECT 1 FROM workspace_exports)
               OR EXISTS (SELECT 1 FROM workspace_closures)
               OR EXISTS (SELECT 1 FROM workspace_recovery_evidence)
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H1-09 with recovery or closure state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    for table_name in reversed(WRITE_GUARDED_TABLES):
        op.execute(
            f"DROP TRIGGER {table_name}_workspace_writable ON {table_name}"
        )
    for table_name in (
        "workspace_exports",
        "workspace_recovery_evidence",
        "workspace_closures",
    ):
        op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION prevent_recovery_evidence_mutation()")
    op.execute("DROP FUNCTION enforce_workspace_write_state()")
    for table_name in reversed(CONTROL_TABLES):
        op.drop_table(table_name)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_workspace_membership_ownership()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            checked_workspace_id UUID;
            checked_organization_id UUID;
            checked_organization_type TEXT;
            active_member_count INTEGER;
            active_owner_count INTEGER;
            personal_member_user_id UUID;
            organization_owner_user_id UUID;
        BEGIN
            checked_workspace_id := COALESCE(NEW.workspace_id, OLD.workspace_id);
            SELECT organization_id
              INTO checked_organization_id
              FROM workspaces
             WHERE workspace_id = checked_workspace_id;
            IF checked_organization_id IS NULL THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            SELECT organization_type
              INTO checked_organization_type
              FROM organizations
             WHERE id = checked_organization_id;
            SELECT
                count(*) FILTER (WHERE status = 'active'),
                count(*) FILTER (
                    WHERE status = 'active' AND role_key = 'workspace_owner'
                ),
                (array_agg(user_id ORDER BY user_id)
                    FILTER (WHERE status = 'active'))[1]
              INTO active_member_count, active_owner_count, personal_member_user_id
              FROM workspace_memberships
             WHERE workspace_id = checked_workspace_id;
            IF active_owner_count < 1 THEN
                RAISE EXCEPTION
                    'workspace must retain at least one active workspace owner';
            END IF;
            IF checked_organization_type = 'personal' THEN
                SELECT user_id
                  INTO organization_owner_user_id
                  FROM organization_memberships
                 WHERE organization_id = checked_organization_id
                   AND role = 'owner'
                   AND status = 'active';
                IF active_member_count <> 1
                   OR personal_member_user_id IS DISTINCT FROM organization_owner_user_id
                THEN
                    RAISE EXCEPTION
                        'personal workspace must have exactly its organization owner';
                END IF;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )
