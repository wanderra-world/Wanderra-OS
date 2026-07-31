"""Add H2-09 connection backfill and controlled cutover evidence."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0021_h2_connection_cutover"
down_revision = "0020_h2_storage_capability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVIDENCE_TABLES = ("connection_backfill_evidence", "capability_cutover_evidence")
ROUTE_TABLES = (
    "email_capability_routes",
    "calendar_capability_routes",
    "storage_capability_routes",
)


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {table}_workspace_isolation ON {table}
        USING (workspace_id = NULLIF(
            current_setting('atlas.workspace_id', TRUE), '')::UUID)
        WITH CHECK (workspace_id = NULLIF(
            current_setting('atlas.workspace_id', TRUE), '')::UUID)
        """)
    op.execute(f"""
        CREATE TRIGGER {table}_workspace_writable
        BEFORE INSERT OR UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()
        """)


def upgrade() -> None:
    for table in ROUTE_TABLES:
        op.add_column(
            table,
            sa.Column("mutation_route", sa.String(16), server_default="legacy", nullable=False),
        )
        op.create_check_constraint(
            f"ck_{table}_mutation_route",
            table,
            "mutation_route IN ('legacy','canonical')",
        )

    op.create_table(
        "connection_backfill_evidence",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_system", sa.String(32), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("evidence_checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "source_system",
            "source_record_id",
            name="pk_connection_backfill_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_connection_backfill_evidence_connection",
        ),
        sa.CheckConstraint(
            "status IN ('mapped','reauthorization_required')",
            name="ck_connection_backfill_evidence_status",
        ),
    )
    op.create_table(
        "capability_cutover_evidence",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(16), nullable=False),
        sa.Column("route_kind", sa.String(16), nullable=False),
        sa.Column("requested_route", sa.String(16), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("matches", sa.Integer(), nullable=False),
        sa.Column("minimum_samples", sa.Integer(), nullable=False),
        sa.Column("maximum_mismatch_rate", sa.String(32), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_capability_cutover_evidence"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_capability_cutover_evidence_connection",
        ),
        sa.CheckConstraint(
            "capability IN ('email','calendar','storage')",
            name="ck_capability_cutover_evidence_capability",
        ),
        sa.CheckConstraint(
            "route_kind IN ('read','mutation')", name="ck_capability_cutover_evidence_route_kind"
        ),
        sa.CheckConstraint(
            "requested_route IN ('legacy','shadow','canonical')",
            name="ck_capability_cutover_evidence_route",
        ),
        sa.CheckConstraint(
            "samples >= 0 AND matches >= 0 AND matches <= samples",
            name="ck_capability_cutover_evidence_metrics",
        ),
    )
    for table in EVIDENCE_TABLES:
        _rls(table)
    op.execute(
        "CREATE RULE capability_cutover_evidence_no_update AS "
        "ON UPDATE TO capability_cutover_evidence DO INSTEAD NOTHING"
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM connection_backfill_evidence)
             OR EXISTS (SELECT 1 FROM capability_cutover_evidence)
             OR EXISTS (SELECT 1 FROM email_capability_routes WHERE mutation_route <> 'legacy')
             OR EXISTS (SELECT 1 FROM calendar_capability_routes WHERE mutation_route <> 'legacy')
             OR EXISTS (SELECT 1 FROM storage_capability_routes WHERE mutation_route <> 'legacy')
          THEN RAISE EXCEPTION
            'cannot downgrade H2-09 with backfill or cutover evidence; use a reviewed forward fix';
          END IF;
        END $$;
        """)
    op.execute("DROP RULE capability_cutover_evidence_no_update ON capability_cutover_evidence")
    for table in reversed(EVIDENCE_TABLES):
        op.execute(f"DROP TRIGGER {table}_workspace_writable ON {table}")
        op.drop_table(table)
    for table in ROUTE_TABLES:
        op.drop_constraint(f"ck_{table}_mutation_route", table, type_="check")
        op.drop_column(table, "mutation_route")
