"""Add H3-06 permission-aware search and context projections.

Revision ID: 0027_h3_search_context
Revises: 0026_h3_governed_memory
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0027_h3_search_context"
down_revision = "0026_h3_governed_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "search_index_generations",
    "search_documents",
    "search_acl_projections",
    "search_embeddings",
    "search_reconciliations",
)


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "vector"


def tenant() -> tuple[sa.Column, ...]:
    return (
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("cell_id", sa.Uuid(), nullable=False),
    )


def workspace_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "organization_id", "cell_id"],
        ["workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id"],
        ondelete="RESTRICT",
        name=name,
    )


def rls(table: str) -> None:
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
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "search_index_generations",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("index_version", sa.String(64), nullable=False),
        sa.Column("chunker_version", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(96), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="building", nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_search_index_generations"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "index_version",
            name="uq_search_index_generation_version",
        ),
        workspace_fk("fk_search_index_generation_workspace"),
        sa.CheckConstraint(
            "status IN ('building','active','disabled','retired')",
            name="ck_search_index_generation_status",
        ),
        sa.CheckConstraint(
            "dimensions > 0 AND policy_version > 0", name="ck_search_index_generation_versions"
        ),
        sa.CheckConstraint(
            "length(manifest_digest) = 64", name="ck_search_index_generation_digest"
        ),
    )
    op.create_table(
        "search_documents",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("owner_user_id", sa.Uuid()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "search_vector",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("chunker_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_search_documents"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "generation_id",
            "identity_digest",
            name="uq_search_document",
        ),
        workspace_fk("fk_search_documents_workspace"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "generation_id"],
            [
                "search_index_generations.organization_id",
                "search_index_generations.workspace_id",
                "search_index_generations.cell_id",
                "search_index_generations.id",
            ],
            ondelete="RESTRICT",
            name="fk_search_documents_generation",
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
            name="fk_search_documents_resource",
        ),
        sa.CheckConstraint(
            "source_kind IN ('resource','document_version','document_chunk','knowledge_claim','memory_item')",
            name="ck_search_documents_source_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active','stale','deleted','quarantined')",
            name="ck_search_documents_status",
        ),
        sa.CheckConstraint(
            "visibility IN ('private','workspace','restricted')",
            name="ck_search_documents_visibility",
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_search_documents_classification",
        ),
        sa.CheckConstraint(
            "source_version > 0 AND policy_version > 0", name="ck_search_documents_versions"
        ),
        sa.CheckConstraint(
            "length(source_digest) = 64 AND length(identity_digest) = 64",
            name="ck_search_documents_digests",
        ),
    )
    op.create_index(
        "ix_search_documents_source",
        "search_documents",
        ["workspace_id", "source_kind", "source_id"],
    )
    op.create_index(
        "ix_search_documents_resource",
        "search_documents",
        ["workspace_id", "resource_id", "status"],
    )
    op.create_index(
        "ix_search_documents_fts", "search_documents", ["search_vector"], postgresql_using="gin"
    )
    op.create_table(
        "search_acl_projections",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("principal_type", sa.String(16), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column(
            "projected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_search_acl_projections"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "document_id",
            "principal_type",
            "principal_id",
            name="uq_search_acl",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "document_id"],
            [
                "search_documents.organization_id",
                "search_documents.workspace_id",
                "search_documents.cell_id",
                "search_documents.id",
            ],
            ondelete="RESTRICT",
            name="fk_search_acl_document",
        ),
        sa.CheckConstraint(
            "principal_type IN ('workspace','user')", name="ck_search_acl_principal_type"
        ),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_search_acl_status"),
        sa.CheckConstraint("policy_version > 0", name="ck_search_acl_policy"),
    )
    op.create_index(
        "ix_search_acl_principal",
        "search_acl_projections",
        ["workspace_id", "principal_type", "principal_id", "status"],
    )
    op.create_table(
        "search_embeddings",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("model_key", sa.String(96), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_search_embeddings"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "document_id",
            "model_key",
            "model_version",
            name="uq_search_embedding",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "document_id"],
            [
                "search_documents.organization_id",
                "search_documents.workspace_id",
                "search_documents.cell_id",
                "search_documents.id",
            ],
            ondelete="RESTRICT",
            name="fk_search_embedding_document",
        ),
        sa.CheckConstraint("dimensions > 0", name="ck_search_embedding_dimensions"),
        sa.CheckConstraint("length(input_digest) = 64", name="ck_search_embedding_digest"),
    )
    op.create_table(
        "search_reconciliations",
        *tenant(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("exception_detail", sa.String(512)),
        sa.Column("checkpoint", sa.LargeBinary()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_search_reconciliations"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "idempotency_key",
            name="uq_search_reconciliation",
        ),
        workspace_fk("fk_search_reconciliation_workspace"),
        sa.CheckConstraint(
            "status IN ('pending','completed','exception')", name="ck_search_reconciliation_status"
        ),
        sa.CheckConstraint("length(input_digest) = 64", name="ck_search_reconciliation_digest"),
    )
    for table in TABLES:
        rls(table)


def downgrade() -> None:
    connection = op.get_bind()
    populated = [
        table
        for table in TABLES
        if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
    ]
    if populated:
        raise RuntimeError(
            "H3-06 search state exists; use a reviewed forward fix or export before downgrade: "
            + ", ".join(populated)
        )
    for table in reversed(TABLES):
        op.drop_table(table)
