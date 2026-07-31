"""Add H2-07 Calendar routing and shadow comparison evidence.

Revision ID: 0019_h2_calendar_capability
Revises: 0018_h2_email_capability
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_h2_calendar_capability"
down_revision: str | Sequence[str] | None = "0018_h2_email_capability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("calendar_capability_routes", "calendar_shadow_comparisons")


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
        "calendar_capability_routes",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("route", sa.String(16), server_default="legacy", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "connection_id",
            name="pk_calendar_capability_routes",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_calendar_capability_routes_connection",
        ),
        sa.CheckConstraint(
            "route IN ('legacy', 'shadow', 'canonical')",
            name="ck_calendar_capability_routes_route",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_calendar_capability_routes_version"
        ),
    )
    op.create_table(
        "calendar_shadow_comparisons",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("equivalent", sa.Boolean(), nullable=False),
        sa.Column(
            "compared_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_calendar_shadow_comparisons"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_calendar_shadow_comparisons_connection",
        ),
        sa.CheckConstraint(
            "operation = 'list'",
            name="ck_calendar_shadow_comparisons_operation",
        ),
    )
    op.create_index(
        "ix_calendar_shadow_comparisons_connection",
        "calendar_shadow_comparisons",
        ["workspace_id", "connection_id", "compared_at"],
    )
    for table in TABLES:
        _rls(table)
    op.execute(
        """
        CREATE RULE calendar_shadow_comparisons_no_update AS
        ON UPDATE TO calendar_shadow_comparisons DO INSTEAD NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM calendar_capability_routes)
               OR EXISTS (SELECT 1 FROM calendar_shadow_comparisons)
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H2-07 with routing evidence; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "DROP RULE calendar_shadow_comparisons_no_update "
        "ON calendar_shadow_comparisons"
    )
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER {table}_workspace_writable ON {table}")
        op.drop_table(table)
