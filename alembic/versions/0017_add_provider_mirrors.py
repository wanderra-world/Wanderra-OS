"""Add H2-04 provider mirrors and external references.

Revision ID: 0017_h2_provider_mirrors
Revises: 0016_h2_oauth_transactions
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_h2_provider_mirrors"
down_revision: str | Sequence[str] | None = "0016_h2_oauth_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "provider_mirrors",
    "provider_external_references",
    "provider_mirror_conflicts",
    "provider_mirror_comparisons",
)


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_workspace_isolation ON {table}
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
    op.execute(
        f"""
        CREATE TRIGGER {table}_workspace_writable
        BEFORE INSERT OR UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()
        """
    )


def upgrade() -> None:
    op.create_table(
        "provider_mirrors",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(96), nullable=False),
        sa.Column("external_id", sa.String(1024), nullable=False),
        sa.Column("provider_version", sa.String(512), nullable=False),
        sa.Column("etag", sa.String(512), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalized_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload_reference", sa.Text(), nullable=True),
        sa.Column("raw_payload_owner", sa.String(96), nullable=True),
        sa.Column("authority", sa.String(32), nullable=False),
        sa.Column(
            "field_authority",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("sync_state", sa.String(32), nullable=False),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_provider_mirrors"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_provider_mirrors_connection",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "connection_id",
            "resource_type",
            "external_id",
            name="uq_provider_mirrors_external_identity",
        ),
        sa.CheckConstraint("version > 0", name="ck_provider_mirrors_version"),
        sa.CheckConstraint(
            "authority IN ('provider_authoritative', 'atlas_authoritative', "
            "'user_resolved', 'mergeable')",
            name="ck_provider_mirrors_authority",
        ),
        sa.CheckConstraint(
            "sync_state IN ('synced', 'conflict', 'tombstoned', 'deleted')",
            name="ck_provider_mirrors_sync_state",
        ),
    )
    op.create_index(
        "ix_provider_mirrors_state",
        "provider_mirrors",
        ["workspace_id", "connection_id", "sync_state"],
    )
    op.create_table(
        "provider_external_references",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mirror_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(96), nullable=False),
        sa.Column("external_id", sa.String(1024), nullable=False),
        sa.Column("canonical_reference_type", sa.String(96), nullable=True),
        sa.Column("canonical_reference_id", sa.Uuid(), nullable=True),
        sa.Column("approval_reference", sa.String(128), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_provider_external_references"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "mirror_id"],
            ["provider_mirrors.workspace_id", "provider_mirrors.id"],
            ondelete="RESTRICT",
            name="fk_provider_external_references_mirror",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "connection_id",
            "resource_type",
            "external_id",
            name="uq_provider_external_references_identity",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "mirror_id",
            name="uq_provider_external_references_mirror",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_provider_external_references_version"
        ),
    )
    op.create_table(
        "provider_mirror_conflicts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mirror_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(96), nullable=False),
        sa.Column("atlas_hash", sa.String(64), nullable=False),
        sa.Column("provider_hash", sa.String(64), nullable=False),
        sa.Column("provider_version", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("resolution", sa.String(32), nullable=True),
        sa.Column("resolution_hash", sa.String(64), nullable=True),
        sa.Column("resolution_idempotency_key", sa.String(128), nullable=True),
        sa.Column("resolution_request_digest", sa.String(64), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_provider_mirror_conflicts"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "mirror_id"],
            ["provider_mirrors.workspace_id", "provider_mirrors.id"],
            ondelete="RESTRICT",
            name="fk_provider_mirror_conflicts_mirror",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_provider_mirror_conflicts_status",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_provider_mirror_conflicts_version"
        ),
    )
    op.create_index(
        "uq_provider_mirror_conflicts_open",
        "provider_mirror_conflicts",
        ["workspace_id", "mirror_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "provider_mirror_comparisons",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mirror_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("conflict_reason", sa.String(96), nullable=True),
        sa.Column("observed_provider_version", sa.String(512), nullable=False),
        sa.Column("observed_hash", sa.String(64), nullable=False),
        sa.Column("mirror_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_provider_mirror_comparisons"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "mirror_id"],
            ["provider_mirrors.workspace_id", "provider_mirrors.id"],
            ondelete="RESTRICT",
            name="fk_provider_mirror_comparisons_mirror",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_provider_mirror_comparisons_idempotency",
        ),
    )
    for table in TABLES:
        _rls(table)
    op.execute(
        """
        CREATE FUNCTION enforce_provider_mirror_invariants()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF (NEW.raw_payload_reference IS NULL)
               <> (NEW.raw_payload_owner IS NULL)
            THEN
                RAISE EXCEPTION 'raw payload reference requires approved owner';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.workspace_id, NEW.id, NEW.connection_id,
                    NEW.resource_type, NEW.external_id, NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.workspace_id, OLD.id, OLD.connection_id,
                    OLD.resource_type, OLD.external_id, OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'provider mirror identity is immutable';
                END IF;
                IF NEW.version <> OLD.version + 1 THEN
                    RAISE EXCEPTION 'provider mirror version is invalid';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER provider_mirrors_enforce_invariants
        BEFORE INSERT OR UPDATE ON provider_mirrors
        FOR EACH ROW EXECUTE FUNCTION enforce_provider_mirror_invariants()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_provider_external_reference_invariants()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            mirror_connection UUID;
            mirror_resource_type TEXT;
            mirror_external_id TEXT;
        BEGIN
            SELECT connection_id, resource_type, external_id
              INTO mirror_connection, mirror_resource_type, mirror_external_id
              FROM provider_mirrors
             WHERE workspace_id = NEW.workspace_id
               AND id = NEW.mirror_id;
            IF mirror_connection IS DISTINCT FROM NEW.connection_id
               OR mirror_resource_type IS DISTINCT FROM NEW.resource_type
               OR mirror_external_id IS DISTINCT FROM NEW.external_id
            THEN
                RAISE EXCEPTION 'provider external reference identity mismatch';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.workspace_id, NEW.id, NEW.mirror_id, NEW.connection_id,
                    NEW.resource_type, NEW.external_id, NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.workspace_id, OLD.id, OLD.mirror_id, OLD.connection_id,
                    OLD.resource_type, OLD.external_id, OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'provider external identity is immutable';
                END IF;
                IF OLD.canonical_reference_id IS NOT NULL
                   AND ROW(
                       NEW.canonical_reference_type, NEW.canonical_reference_id
                   ) IS DISTINCT FROM ROW(
                       OLD.canonical_reference_type, OLD.canonical_reference_id
                   )
                THEN
                    RAISE EXCEPTION 'canonical reference is immutable once linked';
                END IF;
                IF NEW.version <> OLD.version + 1 THEN
                    RAISE EXCEPTION 'external reference version is invalid';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER provider_external_references_enforce_invariants
        BEFORE INSERT OR UPDATE ON provider_external_references
        FOR EACH ROW EXECUTE FUNCTION enforce_provider_external_reference_invariants()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_provider_conflict_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF OLD.status <> 'open' OR NEW.status <> 'resolved'
                   OR NEW.version <> OLD.version + 1
                THEN
                    RAISE EXCEPTION 'provider conflict transition is invalid';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER provider_mirror_conflicts_enforce_transition
        BEFORE UPDATE ON provider_mirror_conflicts
        FOR EACH ROW EXECUTE FUNCTION enforce_provider_conflict_transition()
        """
    )
    op.execute(
        """
        CREATE RULE provider_mirror_comparisons_no_update AS
        ON UPDATE TO provider_mirror_comparisons DO INSTEAD NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM provider_mirrors)
               OR EXISTS (SELECT 1 FROM provider_external_references)
               OR EXISTS (SELECT 1 FROM provider_mirror_conflicts)
               OR EXISTS (SELECT 1 FROM provider_mirror_comparisons)
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H2-04 with provider mirror state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    op.execute("DROP RULE provider_mirror_comparisons_no_update ON provider_mirror_comparisons")
    op.execute(
        "DROP TRIGGER provider_mirror_conflicts_enforce_transition "
        "ON provider_mirror_conflicts"
    )
    op.execute("DROP FUNCTION enforce_provider_conflict_transition()")
    op.execute(
        "DROP TRIGGER provider_external_references_enforce_invariants "
        "ON provider_external_references"
    )
    op.execute("DROP FUNCTION enforce_provider_external_reference_invariants()")
    op.execute(
        "DROP TRIGGER provider_mirrors_enforce_invariants ON provider_mirrors"
    )
    op.execute("DROP FUNCTION enforce_provider_mirror_invariants()")
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER {table}_workspace_writable ON {table}")
        op.drop_table(table)
