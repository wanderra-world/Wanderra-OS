"""Add the constrained H3-01 Resource Graph.

Revision ID: 0022_h3_resource_graph
Revises: 0021_h2_connection_cutover
"""

# ruff: noqa: E501 -- PostgreSQL function bodies retain readable SQL statements.

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0022_h3_resource_graph"
down_revision = "0021_h2_connection_cutover"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT = (
    sa.Column("organization_id", sa.Uuid(), nullable=False),
    sa.Column("workspace_id", sa.Uuid(), nullable=False),
    sa.Column("cell_id", sa.Uuid(), nullable=False),
)
RESOURCE_TYPES = "'contact','company','project','task','communication','meeting','document'"
TABLES = (
    "resource_projections",
    "resources",
    "resource_relationships",
    "resource_tags",
    "resource_attachments",
    "resource_notes",
    "resource_ownerships",
    "resource_grants",
    "resource_external_links",
)


def _tenant_columns() -> tuple[sa.Column, ...]:
    return tuple(column._copy() for column in TENANT)


def _workspace_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "organization_id", "cell_id"],
        ["workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id"],
        ondelete="RESTRICT",
        name=name,
    )


def _resource_fk(name: str, column: str = "resource_id") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "workspace_id", "cell_id", column],
        [
            "resources.organization_id",
            "resources.workspace_id",
            "resources.cell_id",
            "resources.id",
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
        "resource_projections",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_projections"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "resource_id",
            name="uq_resource_projections_resource",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "id",
            "resource_type",
            name="uq_resource_projections_identity_type",
        ),
        sa.CheckConstraint(
            f"resource_type IN ({RESOURCE_TYPES})", name="ck_resource_projections_type"
        ),
        _workspace_fk("fk_resource_projections_workspace"),
    )
    op.create_table(
        "resources",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resources"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "id",
            "resource_type",
            name="uq_resources_identity_type",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "projection_id",
            name="uq_resources_projection",
        ),
        sa.CheckConstraint(f"resource_type IN ({RESOURCE_TYPES})", name="ck_resources_type"),
        sa.CheckConstraint("status IN ('active','deleted')", name="ck_resources_status"),
        sa.CheckConstraint("version > 0", name="ck_resources_version"),
        _workspace_fk("fk_resources_workspace"),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "projection_id", "resource_type"],
            [
                "resource_projections.organization_id",
                "resource_projections.workspace_id",
                "resource_projections.cell_id",
                "resource_projections.id",
                "resource_projections.resource_type",
            ],
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
            name="fk_resources_projection",
        ),
    )
    op.create_foreign_key(
        "fk_resource_projections_resource",
        "resource_projections",
        "resources",
        ["organization_id", "workspace_id", "cell_id", "resource_id", "resource_type"],
        ["organization_id", "workspace_id", "cell_id", "id", "resource_type"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "ix_resources_workspace_type", "resources", ["workspace_id", "resource_type", "status"]
    )

    op.create_table(
        "resource_relationships",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("relationship_type", sa.String(64), nullable=False),
        sa.Column("source_resource_id", sa.Uuid(), nullable=False),
        sa.Column("target_resource_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_relationships"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "relationship_type",
            "source_resource_id",
            "target_resource_id",
            name="uq_resource_relationships_edge",
        ),
        sa.CheckConstraint(
            "source_resource_id <> target_resource_id", name="ck_resource_relationships_distinct"
        ),
        sa.CheckConstraint(
            "status IN ('active','deleted')", name="ck_resource_relationships_status"
        ),
        sa.CheckConstraint("version > 0", name="ck_resource_relationships_version"),
        _workspace_fk("fk_resource_relationships_workspace"),
        _resource_fk("fk_resource_relationships_source", "source_resource_id"),
        _resource_fk("fk_resource_relationships_target", "target_resource_id"),
    )
    op.create_index(
        "ix_resource_relationships_source",
        "resource_relationships",
        ["workspace_id", "source_resource_id", "status"],
    )
    op.create_index(
        "ix_resource_relationships_target",
        "resource_relationships",
        ["workspace_id", "target_resource_id", "status"],
    )

    op.create_table(
        "resource_tags",
        *_tenant_columns(),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(64), nullable=False),
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
            "resource_id",
            "tag",
            name="pk_resource_tags",
        ),
        sa.CheckConstraint(
            "tag = lower(tag) AND length(tag) BETWEEN 1 AND 64", name="ck_resource_tags_value"
        ),
        _resource_fk("fk_resource_tags_resource"),
    )
    op.create_table(
        "resource_attachments",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_resource_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_attachments"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "resource_id",
            "attachment_resource_id",
            name="uq_resource_attachments_pair",
        ),
        _resource_fk("fk_resource_attachments_resource"),
        _resource_fk("fk_resource_attachments_attachment", "attachment_resource_id"),
    )
    op.create_table(
        "resource_notes",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("note_kind", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_reference", sa.String(128)),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_notes"
        ),
        sa.CheckConstraint("note_kind IN ('human','ai')", name="ck_resource_notes_kind"),
        sa.CheckConstraint("length(content) BETWEEN 1 AND 10000", name="ck_resource_notes_content"),
        sa.CheckConstraint(
            "note_kind = 'human' OR model_reference IS NOT NULL",
            name="ck_resource_notes_ai_provenance",
        ),
        _resource_fk("fk_resource_notes_resource"),
    )
    op.create_table(
        "resource_ownerships",
        *_tenant_columns(),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "resource_id",
            name="pk_resource_ownerships",
        ),
        _resource_fk("fk_resource_ownerships_resource"),
    )
    op.create_table(
        "resource_grants",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("grantee_user_id", sa.Uuid(), nullable=False),
        sa.Column("permission_key", sa.String(96), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_grants"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "resource_id",
            "grantee_user_id",
            "permission_key",
            name="uq_resource_grants_subject_permission",
        ),
        sa.CheckConstraint(
            "permission_key IN ('read_content','update_content','delete_content')",
            name="ck_resource_grants_permission",
        ),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_resource_grants_status"),
        _resource_fk("fk_resource_grants_resource"),
    )
    op.create_table(
        "resource_external_links",
        *_tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("external_reference_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_external_links"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "external_reference_id",
            name="uq_resource_external_links_external_reference",
        ),
        _resource_fk("fk_resource_external_links_resource"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "external_reference_id"],
            ["provider_external_references.workspace_id", "provider_external_references.id"],
            ondelete="RESTRICT",
            name="fk_resource_external_links_external_reference",
        ),
    )

    op.execute("""
        CREATE FUNCTION validate_resource_relationship() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE source_type text; target_type text; existing_count integer; maximum_count integer;
        BEGIN
          SELECT resource_type INTO source_type FROM resources
           WHERE organization_id = NEW.organization_id AND workspace_id = NEW.workspace_id
             AND cell_id = NEW.cell_id AND id = NEW.source_resource_id;
          SELECT resource_type INTO target_type FROM resources
           WHERE organization_id = NEW.organization_id AND workspace_id = NEW.workspace_id
             AND cell_id = NEW.cell_id AND id = NEW.target_resource_id;
          IF NEW.relationship_type = 'contact_works_for_company' THEN
            IF source_type <> 'contact' OR target_type <> 'company' THEN RAISE EXCEPTION 'invalid relationship endpoint types'; END IF;
            maximum_count := 1;
          ELSIF NEW.relationship_type = 'project_has_task' THEN
            IF source_type <> 'project' OR target_type <> 'task' THEN RAISE EXCEPTION 'invalid relationship endpoint types'; END IF;
          ELSIF NEW.relationship_type = 'document_attached_to_project' THEN
            IF source_type <> 'document' OR target_type <> 'project' THEN RAISE EXCEPTION 'invalid relationship endpoint types'; END IF;
            maximum_count := 1;
          ELSIF NEW.relationship_type = 'communication_relates_to_project' THEN
            IF source_type <> 'communication' OR target_type <> 'project' THEN RAISE EXCEPTION 'invalid relationship endpoint types'; END IF;
          ELSIF NEW.relationship_type = 'meeting_relates_to_project' THEN
            IF source_type <> 'meeting' OR target_type <> 'project' THEN RAISE EXCEPTION 'invalid relationship endpoint types'; END IF;
          ELSE RAISE EXCEPTION 'relationship type is not registered';
          END IF;
          IF maximum_count IS NOT NULL AND NEW.status = 'active' THEN
            SELECT count(*) INTO existing_count FROM resource_relationships
             WHERE workspace_id = NEW.workspace_id AND relationship_type = NEW.relationship_type
               AND source_resource_id = NEW.source_resource_id AND status = 'active'
               AND id <> NEW.id;
            IF existing_count >= maximum_count THEN RAISE EXCEPTION 'relationship cardinality is exceeded'; END IF;
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute(
        "CREATE TRIGGER resource_relationships_validate BEFORE INSERT OR UPDATE ON resource_relationships FOR EACH ROW EXECUTE FUNCTION validate_resource_relationship()"
    )
    op.execute("""
        CREATE FUNCTION resource_external_link_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF NEW.workspace_id <> OLD.workspace_id OR NEW.external_reference_id <> OLD.external_reference_id
             OR NEW.resource_id <> OLD.resource_id THEN
            RAISE EXCEPTION 'provider external reference identity is immutable';
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute(
        "CREATE TRIGGER resource_external_links_immutable BEFORE UPDATE ON resource_external_links FOR EACH ROW EXECUTE FUNCTION resource_external_link_immutable()"
    )
    for table in TABLES:
        _rls(table)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM resources)
             OR EXISTS (SELECT 1 FROM audit_events WHERE target_type = 'resource')
             OR EXISTS (SELECT 1 FROM outbox_events WHERE aggregate_type = 'resource')
          THEN RAISE EXCEPTION
            'cannot downgrade H3-01 with accepted resource state; use a reviewed forward fix';
          END IF;
        END $$;
    """)
    op.execute("DROP FUNCTION resource_external_link_immutable() CASCADE")
    op.execute("DROP FUNCTION validate_resource_relationship() CASCADE")
    op.drop_constraint(
        "fk_resource_projections_resource", "resource_projections", type_="foreignkey"
    )
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER {table}_workspace_writable ON {table}")
        op.drop_table(table)
