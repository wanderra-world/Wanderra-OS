"""Add H3-04 knowledge claims and rebuildable timeline.

Revision ID: 0025_h3_knowledge_timeline
Revises: 0024_h3_document_custody
"""

# ruff: noqa: E501 -- PostgreSQL policy and rollback bodies remain readable.

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0025_h3_knowledge_timeline"
down_revision = "0024_h3_document_custody"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "knowledge_claims",
    "knowledge_evidence",
    "knowledge_relations",
    "knowledge_source_dispositions",
    "timeline_entries",
    "timeline_checkpoints",
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


def _claim_fk(columns: list[str], name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "workspace_id", "cell_id", *columns],
        [
            "knowledge_claims.organization_id",
            "knowledge_claims.workspace_id",
            "knowledge_claims.cell_id",
            "knowledge_claims.id",
        ],
        ondelete="RESTRICT",
        name=name,
    )


def upgrade() -> None:
    op.create_table(
        "knowledge_claims",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_resource_id", sa.Uuid(), nullable=False),
        sa.Column("predicate", sa.String(160), nullable=False),
        sa.Column("value_type", sa.String(16), nullable=False),
        sa.Column("canonical_value", sa.Text(), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("derivation_digest", sa.String(64), nullable=False),
        sa.Column("confidence_basis_points", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("review_state", sa.String(16), server_default="pending", nullable=False),
        sa.Column("review_reason", sa.String(256)),
        sa.Column("reviewed_by_user_id", sa.Uuid()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("extractor_key", sa.String(96), nullable=False),
        sa.Column("extractor_version", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
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
            "organization_id", "workspace_id", "cell_id", "id", name="pk_knowledge_claims"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "identity_digest",
            name="uq_knowledge_claims_identity",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "subject_resource_id"],
            [
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_claims_subject",
        ),
        _workspace_fk("fk_knowledge_claims_workspace"),
        sa.CheckConstraint(
            "value_type IN ('text','integer','decimal','boolean','instant','uuid')",
            name="ck_knowledge_claims_value_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','contradicted','superseded','invalidated')",
            name="ck_knowledge_claims_status",
        ),
        sa.CheckConstraint(
            "review_state IN ('pending','accepted','rejected')", name="ck_knowledge_claims_review"
        ),
        sa.CheckConstraint(
            "confidence_basis_points BETWEEN 0 AND 10000", name="ck_knowledge_claims_confidence"
        ),
        sa.CheckConstraint("length(identity_digest) = 64", name="ck_knowledge_claims_digest"),
        sa.CheckConstraint(
            "length(derivation_digest) = 64",
            name="ck_knowledge_claims_derivation_digest",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_knowledge_claims_validity",
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_knowledge_claims_classification",
        ),
        sa.CheckConstraint(
            "policy_version > 0 AND state_version > 0", name="ck_knowledge_claims_versions"
        ),
    )
    op.create_index(
        "ix_knowledge_claims_subject",
        "knowledge_claims",
        ["workspace_id", "subject_resource_id", "status"],
    )

    op.create_table(
        "knowledge_evidence",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_chunk_id", sa.Uuid()),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_knowledge_evidence"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "claim_id",
            "source_version_id",
            "span_start",
            "span_end",
            name="uq_knowledge_evidence_span",
        ),
        _claim_fk(["claim_id"], "fk_knowledge_evidence_claim"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "source_version_id"],
            [
                "document_versions.organization_id",
                "document_versions.workspace_id",
                "document_versions.cell_id",
                "document_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_evidence_version",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "source_chunk_id"],
            [
                "document_chunks.organization_id",
                "document_chunks.workspace_id",
                "document_chunks.cell_id",
                "document_chunks.id",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_evidence_chunk",
        ),
        _workspace_fk("fk_knowledge_evidence_workspace"),
        sa.CheckConstraint("length(source_hash) = 64", name="ck_knowledge_evidence_hash"),
        sa.CheckConstraint(
            "span_start >= 0 AND span_end > span_start", name="ck_knowledge_evidence_span"
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_knowledge_evidence_classification",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_knowledge_evidence_policy"),
    )
    op.create_index(
        "ix_knowledge_evidence_source", "knowledge_evidence", ["workspace_id", "source_version_id"]
    )

    op.create_table(
        "knowledge_relations",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("conflicting_claim_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
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
            "organization_id", "workspace_id", "cell_id", "id", name="pk_knowledge_relations"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "claim_id",
            "conflicting_claim_id",
            "relation_type",
            name="uq_knowledge_relations_pair",
        ),
        _claim_fk(["claim_id"], "fk_knowledge_relations_claim"),
        _claim_fk(["conflicting_claim_id"], "fk_knowledge_relations_conflict"),
        _workspace_fk("fk_knowledge_relations_workspace"),
        sa.CheckConstraint(
            "claim_id <> conflicting_claim_id", name="ck_knowledge_relations_distinct"
        ),
        sa.CheckConstraint(
            "relation_type IN ('contradicts','supersedes')", name="ck_knowledge_relations_type"
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_knowledge_relations_classification",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_knowledge_relations_policy"),
    )

    op.create_table(
        "knowledge_source_dispositions",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("exception_code", sa.String(96)),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "id",
            name="pk_knowledge_source_dispositions",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "source_version_id",
            name="uq_knowledge_source_dispositions_source",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "source_version_id"],
            [
                "document_versions.organization_id",
                "document_versions.workspace_id",
                "document_versions.cell_id",
                "document_versions.id",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_source_dispositions_version",
        ),
        _workspace_fk("fk_knowledge_source_dispositions_workspace"),
        sa.CheckConstraint(
            "status IN ('pending','completed','exception')",
            name="ck_knowledge_source_dispositions_status",
        ),
    )

    op.create_table(
        "timeline_entries",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("projection_key", sa.String(96), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_type", sa.String(128), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("source_claim_id", sa.Uuid()),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_timeline_entries"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "source_event_id",
            name="uq_timeline_entries_source",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "resource_id"],
            [
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
            ],
            ondelete="RESTRICT",
            name="fk_timeline_entries_resource",
        ),
        _claim_fk(["source_claim_id"], "fk_timeline_entries_claim"),
        _workspace_fk("fk_timeline_entries_workspace"),
        sa.CheckConstraint(
            "source_sequence > 0 AND projection_version > 0", name="ck_timeline_entries_versions"
        ),
        sa.CheckConstraint(
            "visibility IN ('workspace','restricted')", name="ck_timeline_entries_visibility"
        ),
        sa.CheckConstraint("status IN ('active','removed')", name="ck_timeline_entries_status"),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_timeline_entries_classification",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_timeline_entries_policy"),
    )
    op.create_index(
        "ix_timeline_entries_order",
        "timeline_entries",
        ["workspace_id", "occurred_at", "source_sequence", "source_event_id"],
    )

    op.create_table(
        "timeline_checkpoints",
        *_tenant_columns(),
        sa.Column("projection_key", sa.String(96), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True)),
        sa.Column("last_source_event_id", sa.Uuid()),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "projection_key",
            name="pk_timeline_checkpoints",
        ),
        _workspace_fk("fk_timeline_checkpoints_workspace"),
        sa.CheckConstraint("projection_version > 0", name="ck_timeline_checkpoints_version"),
        sa.CheckConstraint("length(checksum) = 64", name="ck_timeline_checkpoints_checksum"),
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
            "H3-04 knowledge/timeline state exists; use a reviewed forward fix or export before downgrade: "
            + ", ".join(populated)
        )
    for table in reversed(TABLES):
        op.drop_table(table)
