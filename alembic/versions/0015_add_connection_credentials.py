"""Add H2-02 connection credential custody and migration evidence.

Revision ID: 0015_h2_credentials
Revises: 0014_h2_connections
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_h2_credentials"
down_revision: str | Sequence[str] | None = "0014_h2_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("connection_credentials", "credential_migration_inventory")


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


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_connections_id_provider",
        "connections",
        ["workspace_id", "id", "provider_key"],
    )
    op.create_table(
        "connection_credentials",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=96), nullable=False),
        sa.Column("credential_kind", sa.String(length=96), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("envelope_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("source_system", sa.String(length=96), nullable=True),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("source_checksum", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "generation > 0", name="ck_connection_credentials_generation"
        ),
        sa.CheckConstraint("version > 0", name="ck_connection_credentials_version"),
        sa.CheckConstraint(
            "status IN ('shadow_verified', 'active', "
            "'reauthorization_required', 'revoked', 'disabled')",
            name="ck_connection_credentials_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id", "provider_key"],
            ["connections.workspace_id", "connections.id", "connections.provider_key"],
            ondelete="RESTRICT",
            name="fk_connection_credentials_connection_provider",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "envelope_id"],
            ["encrypted_envelopes.workspace_id", "encrypted_envelopes.id"],
            ondelete="RESTRICT",
            name="fk_connection_credentials_envelope",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_connection_credentials"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "connection_id",
            "credential_kind",
            "generation",
            name="uq_connection_credentials_generation",
        ),
    )
    op.create_index(
        "ix_connection_credentials_current",
        "connection_credentials",
        ["workspace_id", "connection_id", "credential_kind", "status"],
    )
    op.create_table(
        "credential_migration_inventory",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("source_system", sa.String(length=96), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("source_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("exception_code", sa.String(length=96), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('eligible', 'migrated', 'verified', "
            "'reauthorization_required', 'failed')",
            name="ck_credential_migration_inventory_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_credential_migration_inventory_connection",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "credential_id"],
            ["connection_credentials.workspace_id", "connection_credentials.id"],
            ondelete="RESTRICT",
            name="fk_credential_migration_inventory_credential",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_credential_migration_inventory"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "source_system",
            "source_record_id",
            name="uq_credential_migration_inventory_source",
        ),
    )
    op.create_index(
        "ix_credential_migration_inventory_status",
        "credential_migration_inventory",
        ["workspace_id", "status"],
    )
    for table_name in TENANT_TABLES:
        _enable_rls(table_name)
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_workspace_writable
            BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()
            """
        )
    op.execute(
        """
        CREATE FUNCTION enforce_connection_credential_context()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            envelope_connection UUID;
            envelope_record UUID;
            envelope_type TEXT;
            expected_type TEXT;
        BEGIN
            IF TG_OP = 'UPDATE' AND ROW(
                NEW.workspace_id, NEW.id, NEW.connection_id, NEW.provider_key,
                NEW.credential_kind, NEW.generation, NEW.envelope_id
            ) IS DISTINCT FROM ROW(
                OLD.workspace_id, OLD.id, OLD.connection_id, OLD.provider_key,
                OLD.credential_kind, OLD.generation, OLD.envelope_id
            ) THEN
                RAISE EXCEPTION 'connection credential identity is immutable';
            END IF;
            SELECT connection_id, record_id, record_type
              INTO envelope_connection, envelope_record, envelope_type
              FROM encrypted_envelopes
             WHERE workspace_id = NEW.workspace_id
               AND id = NEW.envelope_id;
            expected_type := 'connection_credential:' || NEW.provider_key || ':' ||
                NEW.credential_kind || ':' || 'g' || NEW.generation::TEXT;
            IF envelope_connection IS DISTINCT FROM NEW.connection_id
               OR envelope_record IS DISTINCT FROM NEW.id
               OR envelope_type IS DISTINCT FROM expected_type
            THEN
                RAISE EXCEPTION 'connection credential envelope context mismatch';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER connection_credentials_enforce_context
        BEFORE INSERT OR UPDATE ON connection_credentials
        FOR EACH ROW EXECUTE FUNCTION enforce_connection_credential_context()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM connection_credentials)
               OR EXISTS (SELECT 1 FROM credential_migration_inventory)
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H2-02 with credential custody state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER connection_credentials_enforce_context "
        "ON connection_credentials"
    )
    op.execute("DROP FUNCTION enforce_connection_credential_context()")
    for table_name in reversed(TENANT_TABLES):
        op.execute(
            f"DROP TRIGGER {table_name}_workspace_writable ON {table_name}"
        )
        op.drop_table(table_name)
    op.drop_constraint(
        "uq_connections_id_provider", "connections", type_="unique"
    )
