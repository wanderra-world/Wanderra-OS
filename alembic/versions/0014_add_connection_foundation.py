"""Add the H2-01 connection registry and lifecycle foundation.

Revision ID: 0014_h2_connections
Revises: 0013_h1_recovery_closure
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_h2_connections"
down_revision: str | Sequence[str] | None = "0013_h1_recovery_closure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVIDERS = (
    ("google_workspace", 1, "workspace_suite", "Google Workspace"),
)
CONNECTION_KINDS = (
    ("workspace_suite", 1, "Email, calendar, and storage workspace suite"),
)
CAPABILITIES = (
    ("email.read", 1, "Read email resources"),
    ("email.send", 1, "Send email messages"),
    ("calendar.read", 1, "Read calendars and events"),
    ("calendar.write", 1, "Create, update, and delete calendar events"),
    ("storage.read", 1, "Read storage metadata and content"),
    ("storage.write", 1, "Create, update, and delete storage resources"),
)
TENANT_TABLES = ("connections", "connection_capability_grants")


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


def _create_catalogs() -> None:
    op.create_table(
        "provider_registry",
        sa.Column("provider_key", sa.String(length=96), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provider_family", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_provider_registry_version"),
        sa.PrimaryKeyConstraint(
            "provider_key",
            "version",
            name="pk_provider_registry",
        ),
    )
    op.create_table(
        "connection_kinds",
        sa.Column("kind_key", sa.String(length=96), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_connection_kinds_version"),
        sa.PrimaryKeyConstraint(
            "kind_key",
            "version",
            name="pk_connection_kinds",
        ),
    )
    op.create_table(
        "provider_capabilities",
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_provider_capabilities_version"),
        sa.PrimaryKeyConstraint(
            "capability_key",
            "version",
            name="pk_provider_capabilities",
        ),
    )
    op.create_table(
        "connection_kind_capabilities",
        sa.Column("kind_key", sa.String(length=96), nullable=False),
        sa.Column("kind_version", sa.Integer(), nullable=False),
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("capability_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["kind_key", "kind_version"],
            ["connection_kinds.kind_key", "connection_kinds.version"],
            ondelete="RESTRICT",
            name="fk_connection_kind_capabilities_kind",
        ),
        sa.ForeignKeyConstraint(
            ["capability_key", "capability_version"],
            ["provider_capabilities.capability_key", "provider_capabilities.version"],
            ondelete="RESTRICT",
            name="fk_connection_kind_capabilities_capability",
        ),
        sa.PrimaryKeyConstraint(
            "kind_key",
            "kind_version",
            "capability_key",
            "capability_version",
            name="pk_connection_kind_capabilities",
        ),
    )

    providers = sa.table(
        "provider_registry",
        sa.column("provider_key", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("provider_family", sa.String()),
        sa.column("display_name", sa.String()),
    )
    op.bulk_insert(
        providers,
        [
            {
                "provider_key": key,
                "version": version,
                "provider_family": family,
                "display_name": display_name,
            }
            for key, version, family, display_name in PROVIDERS
        ],
    )
    kinds = sa.table(
        "connection_kinds",
        sa.column("kind_key", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        kinds,
        [
            {"kind_key": key, "version": version, "description": description}
            for key, version, description in CONNECTION_KINDS
        ],
    )
    capabilities = sa.table(
        "provider_capabilities",
        sa.column("capability_key", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        capabilities,
        [
            {
                "capability_key": key,
                "version": version,
                "description": description,
            }
            for key, version, description in CAPABILITIES
        ],
    )
    kind_capabilities = sa.table(
        "connection_kind_capabilities",
        sa.column("kind_key", sa.String()),
        sa.column("kind_version", sa.Integer()),
        sa.column("capability_key", sa.String()),
        sa.column("capability_version", sa.Integer()),
    )
    op.bulk_insert(
        kind_capabilities,
        [
            {
                "kind_key": "workspace_suite",
                "kind_version": 1,
                "capability_key": key,
                "capability_version": version,
            }
            for key, version, _ in CAPABILITIES
        ],
    )


def _create_tenant_tables() -> None:
    op.create_unique_constraint(
        "uq_workspaces_id_organization_cell",
        "workspaces",
        ["workspace_id", "organization_id", "cell_id"],
    )
    op.create_table(
        "connections",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("cell_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=96), nullable=False),
        sa.Column("provider_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("connection_kind", sa.String(length=96), nullable=False),
        sa.Column(
            "connection_kind_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("provider_account_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "granted_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("last_material_actor_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("degraded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reauthorization_required_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'active', 'degraded', "
            "'reauthorization_required', 'revoked', 'closed')",
            name="ck_connections_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_connections_version"),
        sa.CheckConstraint(
            """
            (status = 'pending'
                AND activated_at IS NULL
                AND revoked_at IS NULL
                AND closed_at IS NULL)
            OR (status IN ('active', 'degraded')
                AND activated_at IS NOT NULL
                AND revoked_at IS NULL
                AND closed_at IS NULL)
            OR (status = 'reauthorization_required'
                AND revoked_at IS NULL
                AND closed_at IS NULL)
            OR (status = 'revoked'
                AND revoked_at IS NOT NULL
                AND closed_at IS NULL)
            OR (status = 'closed' AND closed_at IS NOT NULL)
            """,
            name="ck_connections_lifecycle_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "organization_id", "cell_id"],
            [
                "workspaces.workspace_id",
                "workspaces.organization_id",
                "workspaces.cell_id",
            ],
            ondelete="RESTRICT",
            name="fk_connections_workspace_placement",
        ),
        sa.ForeignKeyConstraint(
            ["provider_key", "provider_version"],
            ["provider_registry.provider_key", "provider_registry.version"],
            ondelete="RESTRICT",
            name="fk_connections_provider",
        ),
        sa.ForeignKeyConstraint(
            ["connection_kind", "connection_kind_version"],
            ["connection_kinds.kind_key", "connection_kinds.version"],
            ondelete="RESTRICT",
            name="fk_connections_kind",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_connections_creator",
        ),
        sa.ForeignKeyConstraint(
            ["last_material_actor_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_connections_last_actor",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_connections"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider_key",
            "connection_kind",
            "provider_account_id",
            name="uq_connections_workspace_provider_kind_account",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "connection_kind",
            "connection_kind_version",
            name="uq_connections_id_kind",
        ),
    )
    op.create_index(
        "ix_connections_workspace_status",
        "connections",
        ["workspace_id", "status"],
    )
    op.create_table(
        "connection_capability_grants",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("connection_kind", sa.String(length=96), nullable=False),
        sa.Column("connection_kind_version", sa.Integer(), nullable=False),
        sa.Column("capability_key", sa.String(length=96), nullable=False),
        sa.Column("capability_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="granted", nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('granted', 'revoked')",
            name="ck_connection_capability_grants_status",
        ),
        sa.CheckConstraint(
            "(status = 'granted' AND revoked_at IS NULL) "
            "OR (status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_connection_capability_grants_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "connection_id",
                "connection_kind",
                "connection_kind_version",
            ],
            [
                "connections.workspace_id",
                "connections.id",
                "connections.connection_kind",
                "connections.connection_kind_version",
            ],
            ondelete="CASCADE",
            name="fk_connection_capability_grants_connection",
        ),
        sa.ForeignKeyConstraint(
            [
                "connection_kind",
                "connection_kind_version",
                "capability_key",
                "capability_version",
            ],
            [
                "connection_kind_capabilities.kind_key",
                "connection_kind_capabilities.kind_version",
                "connection_kind_capabilities.capability_key",
                "connection_kind_capabilities.capability_version",
            ],
            ondelete="RESTRICT",
            name="fk_connection_capability_grants_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_connection_capability_grants_actor",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "connection_id",
            "capability_key",
            "capability_version",
            name="pk_connection_capability_grants",
        ),
    )
    op.create_index(
        "ix_connection_capability_grants_effective",
        "connection_capability_grants",
        ["workspace_id", "connection_id", "status"],
    )


def _create_invariant_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_connection_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            transition_allowed BOOLEAN;
        BEGIN
            IF ROW(
                NEW.workspace_id,
                NEW.organization_id,
                NEW.cell_id,
                NEW.provider_key,
                NEW.provider_version,
                NEW.connection_kind,
                NEW.connection_kind_version,
                NEW.provider_account_id,
                NEW.created_by_user_id
            ) IS DISTINCT FROM ROW(
                OLD.workspace_id,
                OLD.organization_id,
                OLD.cell_id,
                OLD.provider_key,
                OLD.provider_version,
                OLD.connection_kind,
                OLD.connection_kind_version,
                OLD.provider_account_id,
                OLD.created_by_user_id
            ) THEN
                RAISE EXCEPTION 'connection identity is immutable';
            END IF;
            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'connection version must advance exactly once';
            END IF;
            IF NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;
            transition_allowed := CASE OLD.status
                WHEN 'pending' THEN NEW.status IN (
                    'active', 'reauthorization_required', 'revoked', 'closed'
                )
                WHEN 'active' THEN NEW.status IN (
                    'degraded', 'reauthorization_required', 'revoked', 'closed'
                )
                WHEN 'degraded' THEN NEW.status IN (
                    'active', 'reauthorization_required', 'revoked', 'closed'
                )
                WHEN 'reauthorization_required' THEN NEW.status IN (
                    'active', 'revoked', 'closed'
                )
                WHEN 'revoked' THEN NEW.status = 'closed'
                ELSE FALSE
            END;
            IF NOT transition_allowed THEN
                RAISE EXCEPTION 'connection status transition is invalid';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER connections_enforce_update
        BEFORE UPDATE ON connections
        FOR EACH ROW EXECUTE FUNCTION enforce_connection_update()
        """
    )
    for table_name in TENANT_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_workspace_writable
            BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()
            """
        )


def upgrade() -> None:
    _create_catalogs()
    _create_tenant_tables()
    for table_name in TENANT_TABLES:
        _enable_rls(table_name)
    _create_invariant_triggers()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM connections)
               OR EXISTS (SELECT 1 FROM connection_capability_grants)
               OR EXISTS (
                    SELECT 1 FROM audit_events
                    WHERE action LIKE 'connection.%'
               )
               OR EXISTS (
                    SELECT 1 FROM outbox_events
                    WHERE event_type LIKE 'connection.%'
               )
               OR (SELECT count(*) FROM provider_registry) <> 1
               OR (SELECT count(*) FROM connection_kinds) <> 1
               OR (SELECT count(*) FROM provider_capabilities) <> 6
               OR (SELECT count(*) FROM connection_kind_capabilities) <> 6
               OR EXISTS (
                    SELECT 1 FROM provider_registry
                    WHERE provider_key <> 'google_workspace'
                       OR version <> 1
                       OR NOT active
               )
               OR EXISTS (
                    SELECT 1 FROM connection_kinds
                    WHERE kind_key <> 'workspace_suite'
                       OR version <> 1
                       OR NOT active
               )
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H2-01 with connection state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    for table_name in TENANT_TABLES:
        op.execute(
            f"DROP TRIGGER {table_name}_workspace_writable ON {table_name}"
        )
    op.execute("DROP TRIGGER connections_enforce_update ON connections")
    op.execute("DROP FUNCTION enforce_connection_update()")
    op.drop_table("connection_capability_grants")
    op.drop_index("ix_connections_workspace_status", table_name="connections")
    op.drop_table("connections")
    op.drop_constraint(
        "uq_workspaces_id_organization_cell",
        "workspaces",
        type_="unique",
    )
    op.drop_table("connection_kind_capabilities")
    op.drop_table("provider_capabilities")
    op.drop_table("connection_kinds")
    op.drop_table("provider_registry")
