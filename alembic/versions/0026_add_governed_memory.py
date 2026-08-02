"""Add H3-05 governed memory manager.

Revision ID: 0026_h3_governed_memory
Revises: 0025_h3_knowledge_timeline
"""

# ruff: noqa: E501 -- PostgreSQL policy and constraint bodies remain readable.

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0026_h3_governed_memory"
down_revision = "0025_h3_knowledge_timeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "governed_memory_items",
    "governed_memory_sources",
    "governed_memory_feedback",
    "governed_memory_dispositions",
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


def _memory_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "workspace_id", "cell_id", column],
        [
            "governed_memory_items.organization_id",
            "governed_memory_items.workspace_id",
            "governed_memory_items.cell_id",
            "governed_memory_items.id",
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
        "governed_memory_items",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_kind", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("subject_resource_id", sa.Uuid()),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("confidence_basis_points", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("creation_method", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("human_confirmed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("confirmed_by_user_id", sa.Uuid()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_by_id", sa.Uuid()),
        sa.Column("processor_key", sa.String(96)),
        sa.Column("processor_version", sa.String(64)),
        sa.Column("input_digest", sa.String(64)),
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
            "organization_id", "workspace_id", "cell_id", "id", name="pk_governed_memory_items"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "identity_digest",
            name="uq_governed_memory_identity",
        ),
        _workspace_fk("fk_governed_memory_workspace"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "subject_resource_id"],
            [
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ],
            ondelete="RESTRICT",
            name="fk_governed_memory_subject",
        ),
        _memory_fk("superseded_by_id", "fk_governed_memory_superseded_by"),
        sa.CheckConstraint(
            "memory_kind IN ('preference','decision','summary','working_fact')",
            name="ck_governed_memory_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active','superseded','expired','invalidated','deleted')",
            name="ck_governed_memory_status",
        ),
        sa.CheckConstraint(
            "visibility IN ('private','workspace','restricted')",
            name="ck_governed_memory_visibility",
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_governed_memory_classification",
        ),
        sa.CheckConstraint(
            "confidence_basis_points BETWEEN 0 AND 10000",
            name="ck_governed_memory_confidence",
        ),
        sa.CheckConstraint(
            "policy_version > 0 AND state_version > 0", name="ck_governed_memory_versions"
        ),
        sa.CheckConstraint("length(identity_digest) = 64", name="ck_governed_memory_digest"),
        sa.CheckConstraint(
            "(status = 'superseded' AND superseded_by_id IS NOT NULL) OR "
            "(status <> 'superseded' AND superseded_by_id IS NULL)",
            name="ck_governed_memory_supersession",
        ),
    )
    op.create_index(
        "ix_governed_memory_subject",
        "governed_memory_items",
        ["workspace_id", "subject_resource_id", "status"],
    )
    op.create_index(
        "ix_governed_memory_expiry",
        "governed_memory_items",
        ["workspace_id", "expires_at", "status"],
    )

    op.create_table(
        "governed_memory_sources",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_reference_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_version_id", sa.Uuid()),
        sa.Column("source_claim_id", sa.Uuid()),
        sa.Column("source_resource_id", sa.Uuid()),
        sa.Column("source_memory_id", sa.Uuid()),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_governed_memory_sources"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "memory_id",
            "source_kind",
            "source_reference_id",
            name="uq_governed_memory_source",
        ),
        _memory_fk("memory_id", "fk_governed_memory_sources_memory"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "source_document_version_id"],
            [
                "document_versions.organization_id",
                "document_versions.workspace_id",
                "document_versions.cell_id",
                "document_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_governed_memory_sources_document",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "source_claim_id"],
            [
                "knowledge_claims.organization_id",
                "knowledge_claims.workspace_id",
                "knowledge_claims.cell_id",
                "knowledge_claims.id",
            ],
            ondelete="RESTRICT",
            name="fk_governed_memory_sources_claim",
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
            name="fk_governed_memory_sources_resource",
        ),
        _memory_fk("source_memory_id", "fk_governed_memory_sources_memory_source"),
        _workspace_fk("fk_governed_memory_sources_workspace"),
        sa.CheckConstraint(
            "source_kind IN ('document_version','knowledge_claim','resource','memory_item')",
            name="ck_governed_memory_sources_kind",
        ),
        sa.CheckConstraint(
            "num_nonnulls(source_document_version_id, source_claim_id, source_resource_id, source_memory_id) = 1",
            name="ck_governed_memory_sources_one_target",
        ),
        sa.CheckConstraint(
            "(source_kind = 'document_version' AND source_document_version_id = source_reference_id) OR "
            "(source_kind = 'knowledge_claim' AND source_claim_id = source_reference_id) OR "
            "(source_kind = 'resource' AND source_resource_id = source_reference_id) OR "
            "(source_kind = 'memory_item' AND source_memory_id = source_reference_id)",
            name="ck_governed_memory_sources_target_kind",
        ),
        sa.CheckConstraint("source_version > 0", name="ck_governed_memory_sources_version"),
        sa.CheckConstraint("length(source_digest) = 64", name="ck_governed_memory_sources_digest"),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_governed_memory_sources_classification",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_governed_memory_sources_policy"),
    )
    op.create_index(
        "ix_governed_memory_sources_reference",
        "governed_memory_sources",
        ["workspace_id", "source_reference_id"],
    )

    op.create_table(
        "governed_memory_feedback",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
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
            "organization_id", "workspace_id", "cell_id", "id", name="pk_governed_memory_feedback"
        ),
        _memory_fk("memory_id", "fk_governed_memory_feedback_memory"),
        _workspace_fk("fk_governed_memory_feedback_workspace"),
        sa.CheckConstraint(
            "kind IN ('helpful','incorrect','outdated','sensitive')",
            name="ck_governed_memory_feedback_kind",
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_governed_memory_feedback_classification",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_governed_memory_feedback_policy"),
    )

    op.create_table(
        "governed_memory_dispositions",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("target_status", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("receipt_digest", sa.String(64), nullable=False),
        sa.Column("exception_code", sa.String(96)),
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
            "id",
            name="pk_governed_memory_dispositions",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "memory_id",
            "reason",
            name="uq_governed_memory_disposition",
        ),
        _memory_fk("memory_id", "fk_governed_memory_dispositions_memory"),
        _workspace_fk("fk_governed_memory_dispositions_workspace"),
        sa.CheckConstraint(
            "reason IN ('expired','source_deleted','permission_revoked','user_deleted','workspace_closure','superseded')",
            name="ck_governed_memory_dispositions_reason",
        ),
        sa.CheckConstraint(
            "status IN ('completed','exception')", name="ck_governed_memory_dispositions_status"
        ),
        sa.CheckConstraint(
            "target_status IN ('superseded','expired','invalidated','deleted')",
            name="ck_governed_memory_dispositions_target",
        ),
        sa.CheckConstraint("length(receipt_digest) = 64", name="ck_governed_memory_receipt"),
    )

    for table in TABLES:
        _rls(table)


def downgrade() -> None:
    connection = op.get_bind()
    populated = [
        table
        for table in TABLES
        if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
    ]
    if populated:
        raise RuntimeError(
            "H3-05 governed memory state exists; use a reviewed forward fix or export before downgrade: "
            + ", ".join(populated)
        )
    for table in reversed(TABLES):
        op.drop_table(table)
