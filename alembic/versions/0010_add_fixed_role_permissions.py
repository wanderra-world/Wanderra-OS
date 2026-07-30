"""Add the versioned permission catalog and fixed-role rules.

Revision ID: 0010_h1_authorization
Revises: 0009_h1_workspace_memberships
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_h1_authorization"
down_revision: str | Sequence[str] | None = "0009_h1_workspace_memberships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = (
    ("read_content", "Read workspace content"),
    ("update_content", "Create or update workspace content"),
    ("delete_content", "Delete workspace content"),
    ("manage_workspace", "Manage workspace administration"),
    ("manage_organization", "Manage organization administration"),
)

ALLOW_RULES = {
    "organization_owner": {
        "read_content",
        "update_content",
        "delete_content",
        "manage_workspace",
        "manage_organization",
    },
    "organization_admin": {"manage_organization"},
    "workspace_owner": {
        "read_content",
        "update_content",
        "delete_content",
        "manage_workspace",
    },
    "workspace_admin": {
        "read_content",
        "update_content",
        "delete_content",
        "manage_workspace",
    },
    "member": {"read_content", "update_content"},
    "viewer": {"read_content"},
}

DENY_RULES = {
    "organization_admin": {"read_content"},
    "member": {"delete_content", "manage_workspace"},
    "viewer": {"update_content", "delete_content", "manage_workspace"},
}


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("permission_key", sa.String(length=96), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_permissions_version"),
        sa.PrimaryKeyConstraint(
            "permission_key",
            "version",
            name="pk_permissions",
        ),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("role_version", sa.Integer(), nullable=False),
        sa.Column("permission_key", sa.String(length=96), nullable=False),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        sa.Column("effect", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="ck_role_permissions_effect",
        ),
        sa.ForeignKeyConstraint(
            ["role_key", "role_version"],
            ["fixed_membership_roles.role_key", "fixed_membership_roles.version"],
            ondelete="RESTRICT",
            name="fk_role_permissions_role",
        ),
        sa.ForeignKeyConstraint(
            ["permission_key", "permission_version"],
            ["permissions.permission_key", "permissions.version"],
            ondelete="RESTRICT",
            name="fk_role_permissions_permission",
        ),
        sa.PrimaryKeyConstraint(
            "role_key",
            "role_version",
            "permission_key",
            "permission_version",
            "effect",
            name="pk_role_permissions",
        ),
    )

    permission_table = sa.table(
        "permissions",
        sa.column("permission_key", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("description", sa.Text()),
        sa.column("active", sa.Boolean()),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "permission_key": permission_key,
                "version": 1,
                "description": description,
                "active": True,
            }
            for permission_key, description in PERMISSIONS
        ],
    )

    role_permission_table = sa.table(
        "role_permissions",
        sa.column("role_key", sa.String()),
        sa.column("role_version", sa.Integer()),
        sa.column("permission_key", sa.String()),
        sa.column("permission_version", sa.Integer()),
        sa.column("effect", sa.String()),
    )
    op.bulk_insert(
        role_permission_table,
        [
            {
                "role_key": role_key,
                "role_version": 1,
                "permission_key": permission_key,
                "permission_version": 1,
                "effect": effect,
            }
            for effect, rules in (("allow", ALLOW_RULES), ("deny", DENY_RULES))
            for role_key, permission_keys in rules.items()
            for permission_key in sorted(permission_keys)
        ],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF (SELECT count(*) FROM permissions) <> 5
               OR (SELECT count(*) FROM role_permissions) <> 23
               OR EXISTS (
                    SELECT 1 FROM permissions
                    WHERE version <> 1 OR NOT active
               )
               OR EXISTS (
                    SELECT 1 FROM role_permissions
                    WHERE role_version <> 1
                       OR permission_version <> 1
                       OR effect NOT IN ('allow', 'deny')
               )
               OR EXISTS (
                    SELECT 1 FROM audit_events
                    WHERE action = 'authorization.decided'
               )
               OR EXISTS (
                    SELECT 1 FROM outbox_events
                    WHERE event_type = 'authorization.decided'
               )
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H1-05 with authorization state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    op.drop_table("role_permissions")
    op.drop_table("permissions")
