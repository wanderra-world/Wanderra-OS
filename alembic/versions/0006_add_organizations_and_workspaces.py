"""Add the H1 organization and workspace tenancy foundation.

Revision ID: 0006_h1_org_workspaces
Revises: 0005_add_drive_integration
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_h1_org_workspaces"
down_revision: str | Sequence[str] | None = "0005_add_drive_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIMARY_CELL_ID = "00000000-0000-4000-8000-000000000001"


def _create_ownership_invariants() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_organization_ownership()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            checked_organization_id UUID;
            checked_type TEXT;
            membership_count INTEGER;
            active_owner_count INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'organizations' THEN
                checked_organization_id := COALESCE(NEW.id, OLD.id);
            ELSE
                checked_organization_id := COALESCE(NEW.organization_id, OLD.organization_id);
            END IF;

            SELECT organization_type
              INTO checked_type
              FROM organizations
             WHERE id = checked_organization_id;

            IF checked_type IS NULL THEN
                RETURN COALESCE(NEW, OLD);
            END IF;

            SELECT
                count(*),
                count(*) FILTER (WHERE status = 'active' AND role = 'owner')
              INTO membership_count, active_owner_count
              FROM organization_memberships
             WHERE organization_id = checked_organization_id;

            IF active_owner_count < 1 THEN
                RAISE EXCEPTION 'organization must retain at least one active owner';
            END IF;

            IF checked_type = 'personal' AND membership_count <> 1 THEN
                RAISE EXCEPTION 'personal organization must have exactly one membership';
            END IF;

            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER organizations_require_owner
        AFTER INSERT OR UPDATE OF organization_type ON organizations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_organization_ownership();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER organization_memberships_preserve_owner
        AFTER INSERT OR UPDATE OR DELETE ON organization_memberships
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_organization_ownership();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prohibit_workspace_transfer()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.organization_id <> OLD.organization_id THEN
                RAISE EXCEPTION 'workspace transfer is prohibited in Phase 2';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER workspaces_prohibit_transfer
        BEFORE UPDATE OF organization_id ON workspaces
        FOR EACH ROW EXECUTE FUNCTION prohibit_workspace_transfer();
        """
    )


def _create_audit_immutability() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit events are immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_are_immutable
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();
        """
    )


def _enable_workspace_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table_name}_workspace_isolation ON {table_name}
        USING (
            workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
        )
        WITH CHECK (
            workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        "cells",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_cells_key"),
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
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
            "organization_type IN ('business', 'personal')",
            name="ck_organizations_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'closing', 'closed')",
            name="ck_organizations_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin')",
            name="ck_organization_memberships_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_organization_memberships_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "user_id",
            name="pk_organization_memberships",
        ),
    )
    op.create_index(
        "ix_organization_memberships_user_id",
        "organization_memberships",
        ["user_id"],
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("cell_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("time_zone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("locale", sa.String(length=32), server_default="en", nullable=False),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
            "status IN ('active', 'writes_frozen', 'closing', 'closed')",
            name="ck_workspaces_status",
        ),
        sa.ForeignKeyConstraint(["cell_id"], ["cells.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_workspaces_org_slug"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_workspaces_id_organization",
        ),
    )
    op.create_index("ix_workspaces_cell_id", "workspaces", ["cell_id"])

    op.create_table(
        "audit_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="RESTRICT",
            name="fk_audit_events_workspace",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_workspace_recorded",
        "audit_events",
        ["workspace_id", "recorded_at"],
    )
    op.create_table(
        "outbox_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_sequence", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="RESTRICT",
            name="fk_outbox_events_workspace",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_outbox_events"),
        sa.UniqueConstraint(
            "workspace_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_sequence",
            name="uq_outbox_aggregate_sequence",
        ),
    )
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["published_at", "recorded_at"],
    )

    op.execute(
        f"""
        INSERT INTO cells (id, key, region, status)
        VALUES ('{PRIMARY_CELL_ID}'::uuid, 'primary', 'default', 'active')
        """
    )
    op.execute(
        """
        INSERT INTO organizations (id, organization_type, name, status)
        SELECT
            md5('atlas:organization:' || users.id::text)::uuid,
            'personal',
            COALESCE(NULLIF(users.display_name, ''), users.email) || ' Organization',
            'active'
        FROM users
        """
    )
    op.execute(
        """
        INSERT INTO organization_memberships (
            organization_id,
            user_id,
            role,
            status
        )
        SELECT
            md5('atlas:organization:' || users.id::text)::uuid,
            users.id,
            'owner',
            'active'
        FROM users
        """
    )
    op.execute(
        f"""
        INSERT INTO workspaces (
            id,
            organization_id,
            cell_id,
            name,
            slug,
            status
        )
        SELECT
            md5('atlas:workspace:' || users.id::text)::uuid,
            md5('atlas:organization:' || users.id::text)::uuid,
            '{PRIMARY_CELL_ID}'::uuid,
            COALESCE(NULLIF(users.display_name, ''), users.email) || ' Workspace',
            'personal-' || replace(users.id::text, '-', ''),
            'active'
        FROM users
        """
    )
    op.execute(
        """
        INSERT INTO audit_events (
            workspace_id,
            id,
            actor_type,
            actor_id,
            action,
            target_type,
            target_id,
            outcome,
            details
        )
        SELECT
            workspaces.id,
            md5('atlas:audit:workspace-created:' || workspaces.id::text)::uuid,
            'migration',
            NULL,
            'workspace.created',
            'workspace',
            workspaces.id,
            'success',
            jsonb_build_object('migration', '0006_h1_org_workspaces')
        FROM workspaces
        """
    )
    op.execute(
        """
        INSERT INTO outbox_events (
            workspace_id,
            id,
            event_type,
            schema_version,
            aggregate_type,
            aggregate_id,
            aggregate_sequence,
            payload
        )
        SELECT
            workspaces.id,
            md5('atlas:outbox:workspace-created:' || workspaces.id::text)::uuid,
            'atlas.workspace.created',
            1,
            'workspace',
            workspaces.id,
            1,
            jsonb_build_object(
                'workspace_id', workspaces.id,
                'organization_id', workspaces.organization_id,
                'cell_id', workspaces.cell_id
            )
        FROM workspaces
        """
    )

    _create_ownership_invariants()
    _create_audit_immutability()

    op.execute("ALTER TABLE workspaces RENAME COLUMN id TO workspace_id")
    _enable_workspace_rls("workspaces")
    _enable_workspace_rls("audit_events")
    _enable_workspace_rls("outbox_events")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS outbox_events_workspace_isolation ON outbox_events")
    op.execute("DROP POLICY IF EXISTS audit_events_workspace_isolation ON audit_events")
    op.execute("DROP POLICY IF EXISTS workspaces_workspace_isolation ON workspaces")
    op.execute("DROP TRIGGER IF EXISTS audit_events_are_immutable ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_event_mutation()")
    op.execute("DROP TRIGGER IF EXISTS workspaces_prohibit_transfer ON workspaces")
    op.execute("DROP FUNCTION IF EXISTS prohibit_workspace_transfer()")
    op.execute(
        "DROP TRIGGER IF EXISTS organization_memberships_preserve_owner "
        "ON organization_memberships"
    )
    op.execute("DROP TRIGGER IF EXISTS organizations_require_owner ON organizations")
    op.execute("DROP FUNCTION IF EXISTS enforce_organization_ownership()")
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_audit_events_workspace_recorded", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_workspaces_cell_id", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index(
        "ix_organization_memberships_user_id",
        table_name="organization_memberships",
    )
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    op.drop_table("cells")
