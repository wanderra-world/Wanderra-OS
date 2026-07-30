"""Add canonical workspace memberships and fixed role classifications.

Revision ID: 0009_h1_workspace_memberships
Revises: 0008_h1_identity_lifecycle
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_h1_workspace_memberships"
down_revision: str | Sequence[str] | None = "0008_h1_identity_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIXED_ROLES = (
    ("organization_owner", "organization"),
    ("organization_admin", "organization"),
    ("workspace_owner", "workspace"),
    ("workspace_admin", "workspace"),
    ("member", "workspace"),
    ("viewer", "workspace"),
)


def _enable_rls() -> None:
    op.execute("ALTER TABLE workspace_memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workspace_memberships FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workspace_memberships_workspace_isolation
        ON workspace_memberships
        USING (
            workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
        )
        WITH CHECK (
            workspace_id = NULLIF(current_setting('atlas.workspace_id', TRUE), '')::UUID
        )
        """
    )


def _create_workspace_ownership_invariants() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_workspace_membership_ownership()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            checked_workspace_id UUID;
            checked_organization_id UUID;
            checked_organization_type TEXT;
            active_member_count INTEGER;
            active_owner_count INTEGER;
            personal_member_user_id UUID;
            organization_owner_user_id UUID;
        BEGIN
            checked_workspace_id := CASE
                WHEN TG_TABLE_NAME = 'workspaces'
                THEN COALESCE(NEW.workspace_id, OLD.workspace_id)
                ELSE COALESCE(NEW.workspace_id, OLD.workspace_id)
            END;

            SELECT organization_id
              INTO checked_organization_id
              FROM workspaces
             WHERE workspace_id = checked_workspace_id;

            IF checked_organization_id IS NULL THEN
                RETURN COALESCE(NEW, OLD);
            END IF;

            SELECT organization_type
              INTO checked_organization_type
              FROM organizations
             WHERE id = checked_organization_id;

            SELECT
                count(*) FILTER (WHERE status = 'active'),
                count(*) FILTER (
                    WHERE status = 'active' AND role_key = 'workspace_owner'
                ),
                (array_agg(user_id ORDER BY user_id)
                    FILTER (WHERE status = 'active'))[1]
              INTO active_member_count, active_owner_count, personal_member_user_id
              FROM workspace_memberships
             WHERE workspace_id = checked_workspace_id;

            IF active_owner_count < 1 THEN
                RAISE EXCEPTION
                    'workspace must retain at least one active workspace owner';
            END IF;

            IF checked_organization_type = 'personal' THEN
                SELECT user_id
                  INTO organization_owner_user_id
                  FROM organization_memberships
                 WHERE organization_id = checked_organization_id
                   AND role = 'owner'
                   AND status = 'active';

                IF active_member_count <> 1
                   OR personal_member_user_id IS DISTINCT FROM organization_owner_user_id
                THEN
                    RAISE EXCEPTION
                        'personal workspace must have exactly its organization owner';
                END IF;
            END IF;

            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER workspaces_require_membership_owner
        AFTER INSERT OR UPDATE OF organization_id ON workspaces
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_workspace_membership_ownership()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER workspace_memberships_preserve_owner
        AFTER INSERT OR UPDATE OR DELETE ON workspace_memberships
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_workspace_membership_ownership()
        """
    )


def upgrade() -> None:
    op.create_table(
        "fixed_membership_roles",
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope IN ('organization', 'workspace')",
            name="ck_fixed_membership_roles_scope",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_fixed_membership_roles_version",
        ),
        sa.PrimaryKeyConstraint(
            "role_key",
            "version",
            name="pk_fixed_membership_roles",
        ),
    )
    fixed_roles = sa.table(
        "fixed_membership_roles",
        sa.column("role_key", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("scope", sa.String()),
        sa.column("active", sa.Boolean()),
    )
    op.bulk_insert(
        fixed_roles,
        [
            {"role_key": key, "version": 1, "scope": scope, "active": True}
            for key, scope in FIXED_ROLES
        ],
    )

    op.create_table(
        "workspace_memberships",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("role_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("invitation_token_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_invitation_token_id", sa.Uuid(), nullable=True),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=128), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
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
            """
            role_key IN ('workspace_owner', 'workspace_admin', 'member', 'viewer')
            """,
            name="ck_workspace_memberships_workspace_role",
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_workspace_memberships_status",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_workspace_memberships_version",
        ),
        sa.CheckConstraint(
            "origin IN ('direct', 'invitation', 'migration')",
            name="ck_workspace_memberships_origin",
        ),
        sa.CheckConstraint(
            """
            (
                status = 'invited'
                AND activated_at IS NULL
                AND revoked_at IS NULL
            )
            OR
            (
                status IN ('active', 'suspended')
                AND activated_at IS NOT NULL
                AND revoked_at IS NULL
            )
            OR
            (
                status = 'revoked'
                AND revoked_at IS NOT NULL
            )
            """,
            name="ck_workspace_memberships_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["workspaces.workspace_id", "workspaces.organization_id"],
            ondelete="RESTRICT",
            name="fk_workspace_memberships_workspace_organization",
        ),
        sa.ForeignKeyConstraint(
            ["role_key", "role_version"],
            ["fixed_membership_roles.role_key", "fixed_membership_roles.version"],
            ondelete="RESTRICT",
            name="fk_workspace_memberships_fixed_role",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "invitation_token_id"],
            [
                "identity_lifecycle_tokens.workspace_id",
                "identity_lifecycle_tokens.id",
            ],
            ondelete="RESTRICT",
            name="fk_workspace_memberships_invitation",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "accepted_invitation_token_id"],
            [
                "identity_lifecycle_tokens.workspace_id",
                "identity_lifecycle_tokens.id",
            ],
            ondelete="RESTRICT",
            name="fk_workspace_memberships_accepted_invitation",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_workspace_memberships",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_memberships_workspace_user",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "invitation_token_id",
            name="uq_workspace_memberships_invitation",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "accepted_invitation_token_id",
            name="uq_workspace_memberships_accepted_invitation",
        ),
    )
    op.create_index(
        "ix_workspace_memberships_user_status",
        "workspace_memberships",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_workspace_memberships_workspace_role_status",
        "workspace_memberships",
        ["workspace_id", "role_key", "status"],
    )
    _enable_rls()

    op.execute(
        """
        INSERT INTO workspace_memberships (
            workspace_id,
            id,
            organization_id,
            user_id,
            role_key,
            role_version,
            status,
            version,
            activated_at,
            origin
        )
        SELECT
            workspaces.workspace_id,
            md5('atlas:workspace-membership:' || workspaces.workspace_id::text)::uuid,
            workspaces.organization_id,
            owners.user_id,
            'workspace_owner',
            1,
            'active',
            1,
            now(),
            'migration'
        FROM workspaces
        JOIN LATERAL (
            SELECT organization_memberships.user_id
            FROM organization_memberships
            WHERE organization_memberships.organization_id = workspaces.organization_id
              AND organization_memberships.role = 'owner'
              AND organization_memberships.status = 'active'
            ORDER BY organization_memberships.user_id
            LIMIT 1
        ) AS owners ON TRUE
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
            workspace_id,
            md5('atlas:audit:membership-migrated:' || id::text)::uuid,
            'migration',
            NULL,
            'membership.migrated',
            'workspace_membership',
            id,
            'success',
            jsonb_build_object(
                'migration', '0009_h1_workspace_memberships',
                'organization_id', organization_id,
                'user_id', user_id,
                'role_key', role_key,
                'role_version', role_version
            )
        FROM workspace_memberships
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
            workspace_id,
            md5('atlas:outbox:membership-migrated:' || id::text)::uuid,
            'membership.migrated',
            1,
            'workspace_membership',
            id,
            1,
            jsonb_build_object(
                'migration', '0009_h1_workspace_memberships',
                'membership_id', id,
                'organization_id', organization_id,
                'user_id', user_id,
                'role_key', role_key,
                'role_version', role_version
            )
        FROM workspace_memberships
        """
    )
    _create_workspace_ownership_invariants()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM workspace_memberships
                WHERE origin <> 'migration'
                   OR role_key <> 'workspace_owner'
                   OR role_version <> 1
                   OR status <> 'active'
                   OR version <> 1
                   OR invitation_token_id IS NOT NULL
                   OR accepted_invitation_token_id IS NOT NULL
                   OR suspended_at IS NOT NULL
                   OR revoked_at IS NOT NULL
                   OR revocation_reason IS NOT NULL
            )
            OR EXISTS (
                SELECT 1
                FROM fixed_membership_roles
                WHERE version <> 1 OR NOT active
            )
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H1-04 with membership lifecycle state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS workspace_memberships_preserve_owner
        ON workspace_memberships
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS workspaces_require_membership_owner
        ON workspaces
        """
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_workspace_membership_ownership()")
    op.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_are_immutable")
    op.execute(
        """
        DELETE FROM audit_events
        WHERE action = 'membership.migrated'
          AND details ->> 'migration' = '0009_h1_workspace_memberships'
        """
    )
    op.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_are_immutable")
    op.execute(
        """
        DELETE FROM outbox_events
        WHERE event_type = 'membership.migrated'
          AND payload ->> 'migration' = '0009_h1_workspace_memberships'
        """
    )
    op.execute(
        """
        DROP POLICY IF EXISTS workspace_memberships_workspace_isolation
        ON workspace_memberships
        """
    )
    op.drop_index(
        "ix_workspace_memberships_workspace_role_status",
        table_name="workspace_memberships",
    )
    op.drop_index(
        "ix_workspace_memberships_user_status",
        table_name="workspace_memberships",
    )
    op.drop_table("workspace_memberships")
    op.drop_table("fixed_membership_roles")
