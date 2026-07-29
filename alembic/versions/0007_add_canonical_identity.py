"""Add canonical identity state and external identity links.

Revision ID: 0007_h1_canonical_identity
Revises: 0006_h1_org_workspaces
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_h1_canonical_identity"
down_revision: str | Sequence[str] | None = "0006_h1_org_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIMARY_CELL_ID = "00000000-0000-4000-8000-000000000001"


def _preserve_h1_01_ownership_for_all_users() -> None:
    """Backfill H1-01 ownership for users created between the two migrations."""

    op.execute(
        """
        INSERT INTO organizations (id, organization_type, name, status)
        SELECT
            md5('atlas:organization:' || users.id::text)::uuid,
            'personal',
            COALESCE(NULLIF(users.display_name, ''), users.email) || ' Organization',
            'active'
        FROM users
        ON CONFLICT (id) DO NOTHING
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
        ON CONFLICT (organization_id, user_id) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO workspaces (
            workspace_id,
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
        ON CONFLICT (workspace_id) DO NOTHING
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
            md5('atlas:workspace:' || users.id::text)::uuid,
            md5(
                'atlas:audit:workspace-created:'
                || md5('atlas:workspace:' || users.id::text)::uuid::text
            )::uuid,
            'migration',
            NULL,
            'workspace.created',
            'workspace',
            md5('atlas:workspace:' || users.id::text)::uuid,
            'success',
            jsonb_build_object('migration', '0006_h1_org_workspaces')
        FROM users
        ON CONFLICT (workspace_id, id) DO NOTHING
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
            md5('atlas:workspace:' || users.id::text)::uuid,
            md5(
                'atlas:outbox:workspace-created:'
                || md5('atlas:workspace:' || users.id::text)::uuid::text
            )::uuid,
            'atlas.workspace.created',
            1,
            'workspace',
            md5('atlas:workspace:' || users.id::text)::uuid,
            1,
            jsonb_build_object(
                'workspace_id', md5('atlas:workspace:' || users.id::text)::uuid,
                'organization_id', md5('atlas:organization:' || users.id::text)::uuid,
                'cell_id', workspaces.cell_id
            )
        FROM users
        JOIN workspaces
          ON workspaces.workspace_id =
             md5('atlas:workspace:' || users.id::text)::uuid
        ON CONFLICT (workspace_id, id) DO NOTHING
        """
    )


def _record_identity_migration() -> None:
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
            md5('atlas:workspace:' || users.id::text)::uuid,
            md5('atlas:audit:identity-migrated:' || users.id::text)::uuid,
            'migration',
            NULL,
            'identity.migrated',
            'user',
            users.id,
            'success',
            jsonb_build_object('migration', '0007_h1_canonical_identity')
        FROM users
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
            md5('atlas:workspace:' || users.id::text)::uuid,
            md5('atlas:outbox:identity-migrated:' || users.id::text)::uuid,
            'atlas.identity.migrated',
            1,
            'identity',
            users.id,
            1,
            jsonb_build_object(
                'migration', '0007_h1_canonical_identity',
                'user_id', users.id,
                'workspace_id', md5('atlas:workspace:' || users.id::text)::uuid
            )
        FROM users
        """
    )


def upgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_source",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="active",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_users_status",
        "users",
        "status IN ('active', 'suspended', 'disabled')",
    )
    op.create_check_constraint(
        "ck_users_positive_version",
        "users",
        "version > 0",
    )
    op.create_check_constraint(
        "ck_users_email_verification_provenance",
        "users",
        """
        (
            email_verified
            AND email_verified_at IS NOT NULL
            AND email_verification_source IS NOT NULL
        )
        OR
        (
            NOT email_verified
            AND email_verified_at IS NULL
            AND email_verification_source IS NULL
        )
        """,
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "external_identity_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "email_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "email_verification_source",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "linked_at",
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
            "status IN ('active', 'review_pending', 'revoked')",
            name="ck_external_identity_links_status",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_external_identity_links_positive_version",
        ),
        sa.CheckConstraint(
            "btrim(issuer) <> '' AND btrim(subject) <> ''",
            name="ck_external_identity_links_issuer_subject_present",
        ),
        sa.CheckConstraint(
            """
            (
                email_verified
                AND email IS NOT NULL
                AND email_verified_at IS NOT NULL
                AND email_verification_source IS NOT NULL
            )
            OR
            (
                NOT email_verified
                AND email_verified_at IS NULL
                AND email_verification_source IS NULL
            )
            """,
            name="ck_external_identity_links_email_verification_provenance",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issuer",
            "subject",
            name="uq_external_identity_links_issuer_subject",
        ),
    )
    op.create_index(
        "ix_external_identity_links_user_id",
        "external_identity_links",
        ["user_id"],
    )
    op.create_index(
        "ix_external_identity_links_email",
        "external_identity_links",
        ["email"],
    )

    _preserve_h1_01_ownership_for_all_users()
    _record_identity_migration()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM external_identity_links) THEN
                RAISE EXCEPTION
                    'cannot downgrade H1-02 with external identity links; '
                    'use a reviewed forward fix';
            END IF;
            IF EXISTS (
                SELECT email
                FROM users
                GROUP BY email
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot restore unique user email index while duplicates exist; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )

    op.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_are_immutable")
    op.execute(
        """
        DELETE FROM audit_events
        WHERE action = 'identity.migrated'
          AND details ->> 'migration' = '0007_h1_canonical_identity'
        """
    )
    op.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_are_immutable")
    op.execute(
        """
        DELETE FROM outbox_events
        WHERE event_type = 'atlas.identity.migrated'
          AND payload ->> 'migration' = '0007_h1_canonical_identity'
        """
    )

    op.drop_index(
        "ix_external_identity_links_email",
        table_name="external_identity_links",
    )
    op.drop_index(
        "ix_external_identity_links_user_id",
        table_name="external_identity_links",
    )
    op.drop_table("external_identity_links")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_constraint(
        "ck_users_email_verification_provenance",
        "users",
        type_="check",
    )
    op.drop_constraint("ck_users_positive_version", "users", type_="check")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "version")
    op.drop_column("users", "status")
    op.drop_column("users", "email_verification_source")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
    op.create_index("ix_users_email", "users", ["email"], unique=True)
