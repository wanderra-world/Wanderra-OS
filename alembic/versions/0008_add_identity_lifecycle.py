"""Add revocable sessions and identity lifecycle state.

Revision ID: 0008_h1_identity_lifecycle
Revises: 0007_h1_canonical_identity
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0008_h1_identity_lifecycle"
down_revision: str | Sequence[str] | None = "0007_h1_canonical_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls(table_name: str) -> None:
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
    op.add_column(
        "users",
        sa.Column(
            "mfa_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "external_identity_links",
        sa.Column("proofed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_identity_links",
        sa.Column("proof_reference", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "external_identity_links",
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_external_identity_links_review_evidence",
        "external_identity_links",
        """
        (
            status = 'review_pending'
            AND proofed_at IS NOT NULL
            AND proof_reference IS NOT NULL
            AND review_expires_at IS NOT NULL
        )
        OR status <> 'review_pending'
        """,
    )

    op.create_table(
        "identity_sessions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("authentication_strength", sa.String(length=32), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mfa_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "authentication_strength IN ('oidc', 'password', 'mfa')",
            name="ck_identity_sessions_authentication_strength",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_identity_sessions_workspace",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_identity_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_identity_sessions_token_hash"),
    )
    op.create_index(
        "ix_identity_sessions_user_active",
        "identity_sessions",
        ["user_id", "revoked_at", "expires_at"],
    )
    op.create_table(
        "identity_lifecycle_tokens",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("issued_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('invitation', 'recovery')",
            name="ck_identity_lifecycle_tokens_purpose",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_identity_lifecycle_tokens_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_identity_lifecycle_tokens",
        ),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_identity_lifecycle_tokens_token_hash",
        ),
    )
    op.create_index(
        "ix_identity_lifecycle_tokens_user_purpose",
        "identity_lifecycle_tokens",
        ["user_id", "purpose", "consumed_at", "revoked_at"],
    )
    op.create_table(
        "security_notifications",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("destination_hint", sa.String(length=320), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_security_notifications_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_security_notifications_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_security_notifications",
        ),
    )
    op.create_index(
        "ix_security_notifications_pending",
        "security_notifications",
        ["status", "created_at"],
    )
    _enable_rls("identity_sessions")
    _enable_rls("identity_lifecycle_tokens")
    _enable_rls("security_notifications")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM identity_sessions)
               OR EXISTS (SELECT 1 FROM identity_lifecycle_tokens)
               OR EXISTS (SELECT 1 FROM security_notifications)
               OR EXISTS (
                    SELECT 1 FROM external_identity_links
                    WHERE proofed_at IS NOT NULL
                       OR proof_reference IS NOT NULL
                       OR review_expires_at IS NOT NULL
               )
               OR EXISTS (SELECT 1 FROM users WHERE mfa_required) THEN
                RAISE EXCEPTION
                    'cannot downgrade H1-03 with lifecycle state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    op.drop_index(
        "ix_security_notifications_pending",
        table_name="security_notifications",
    )
    op.drop_table("security_notifications")
    op.drop_index(
        "ix_identity_lifecycle_tokens_user_purpose",
        table_name="identity_lifecycle_tokens",
    )
    op.drop_table("identity_lifecycle_tokens")
    op.drop_index(
        "ix_identity_sessions_user_active",
        table_name="identity_sessions",
    )
    op.drop_table("identity_sessions")
    op.drop_constraint(
        "ck_external_identity_links_review_evidence",
        "external_identity_links",
        type_="check",
    )
    op.drop_column("external_identity_links", "review_expires_at")
    op.drop_column("external_identity_links", "proof_reference")
    op.drop_column("external_identity_links", "proofed_at")
    op.drop_column("users", "mfa_required")
