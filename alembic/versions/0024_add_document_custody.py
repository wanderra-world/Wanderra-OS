"""Add H3-03 immutable document custody and governed derivation.

Revision ID: 0024_h3_document_custody
Revises: 0023_h3_durable_execution
"""

# ruff: noqa: E501 -- PostgreSQL policy and rollback bodies remain readable.

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0024_h3_document_custody"
down_revision = "0023_h3_durable_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "documents",
    "document_versions",
    "document_derivatives",
    "document_chunks",
    "document_deletions",
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


def upgrade() -> None:
    op.create_table(
        "documents",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("classification_policy_version", sa.Integer(), nullable=False),
        sa.Column("legal_hold", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True)),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_documents"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "resource_id",
            name="uq_documents_resource",
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
            name="fk_documents_resource",
        ),
        _workspace_fk("fk_documents_workspace"),
        sa.CheckConstraint("status IN ('active','deleted')", name="ck_documents_status"),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_documents_classification",
        ),
        sa.CheckConstraint("classification_policy_version > 0", name="ck_documents_policy"),
        sa.CheckConstraint("state_version > 0", name="ck_documents_state_version"),
    )
    op.create_index("ix_documents_workspace_status", "documents", ["workspace_id", "status"])

    op.create_table(
        "document_versions",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("quarantine_key", sa.String(1024), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("custody_status", sa.String(16), server_default="quarantined", nullable=False),
        sa.Column("malware_verdict", sa.String(16), server_default="pending", nullable=False),
        sa.Column("media_type_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("verifier_version", sa.String(128)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("classification_policy_version", sa.Integer(), nullable=False),
        sa.Column("encryption_key_version", sa.Integer(), nullable=False),
        sa.Column("source_external_reference_id", sa.Uuid()),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_document_versions"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "document_id",
            "version_number",
            name="uq_document_versions_number",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "document_id",
            "content_hash",
            name="uq_document_versions_hash",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "document_id"],
            [
                "documents.organization_id",
                "documents.workspace_id",
                "documents.cell_id",
                "documents.id",
            ],
            ondelete="RESTRICT",
            name="fk_document_versions_document",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_external_reference_id"],
            ["provider_external_references.workspace_id", "provider_external_references.id"],
            ondelete="RESTRICT",
            name="fk_document_versions_external_reference",
        ),
        _workspace_fk("fk_document_versions_workspace"),
        sa.CheckConstraint("version_number > 0", name="ck_document_versions_number"),
        sa.CheckConstraint("size_bytes > 0", name="ck_document_versions_size"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_document_versions_hash"),
        sa.CheckConstraint(
            "custody_status IN ('quarantined','verified','rejected','deleted')",
            name="ck_document_versions_custody",
        ),
        sa.CheckConstraint(
            "malware_verdict IN ('pending','clean','infected','error')",
            name="ck_document_versions_malware",
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_document_versions_classification",
        ),
        sa.CheckConstraint(
            "classification_policy_version > 0 AND encryption_key_version > 0",
            name="ck_document_versions_versions",
        ),
    )
    op.create_index(
        "ix_document_versions_document",
        "document_versions",
        ["workspace_id", "document_id", "version_number"],
    )

    op.create_table(
        "document_derivatives",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("derivative_kind", sa.String(64), nullable=False),
        sa.Column("processor_key", sa.String(96), nullable=False),
        sa.Column("processor_version", sa.String(64), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(1024)),
        sa.Column("status", sa.String(16), server_default="verified", nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("extraction_job_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_document_derivatives"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "source_version_id",
            "input_digest",
            name="uq_document_derivatives_input",
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
            name="fk_document_derivatives_version",
        ),
        _workspace_fk("fk_document_derivatives_workspace"),
        sa.CheckConstraint(
            "length(input_digest) = 64", name="ck_document_derivatives_input_digest"
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64", name="ck_document_derivatives_content_hash"
        ),
        sa.CheckConstraint(
            "status IN ('verified','deleted')", name="ck_document_derivatives_status"
        ),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_document_derivatives_classification",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_document_derivatives_policy"),
    )
    op.create_index(
        "ix_document_derivatives_source",
        "document_derivatives",
        ["workspace_id", "source_version_id", "status"],
    )

    op.create_table(
        "document_chunks",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("derivative_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_document_chunks"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "derivative_id",
            "position",
            name="uq_document_chunks_position",
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
            name="fk_document_chunks_version",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "derivative_id"],
            [
                "document_derivatives.organization_id",
                "document_derivatives.workspace_id",
                "document_derivatives.cell_id",
                "document_derivatives.id",
            ],
            ondelete="RESTRICT",
            name="fk_document_chunks_derivative",
        ),
        _workspace_fk("fk_document_chunks_workspace"),
        sa.CheckConstraint("position >= 0", name="ck_document_chunks_position"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_document_chunks_hash"),
        sa.CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ck_document_chunks_classification",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_document_chunks_policy"),
    )

    op.create_table(
        "document_deletions",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("disposition", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("exception_code", sa.String(96)),
        sa.Column("deletion_job_id", sa.Uuid()),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_document_deletions"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "document_id"],
            [
                "documents.organization_id",
                "documents.workspace_id",
                "documents.cell_id",
                "documents.id",
            ],
            ondelete="RESTRICT",
            name="fk_document_deletions_document",
        ),
        _workspace_fk("fk_document_deletions_workspace"),
        sa.CheckConstraint(
            "status IN ('pending','blocked','completed','exception')",
            name="ck_document_deletions_status",
        ),
        sa.CheckConstraint(
            "disposition IN ('legal_hold','retention','eligible')",
            name="ck_document_deletions_disposition",
        ),
    )
    op.create_index(
        "ix_document_deletions_document",
        "document_deletions",
        ["workspace_id", "document_id", "requested_at"],
    )

    for table in TABLES:
        _rls(table)


def downgrade() -> None:
    connection = op.get_bind()
    populated = any(
        bool(connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")).scalar())
        for table in TABLES
    )
    if populated:
        raise RuntimeError(
            "H3-03 custody state exists; disable processors and use a reviewed forward fix or export"
        )
    for table in reversed(TABLES):
        op.drop_table(table)
