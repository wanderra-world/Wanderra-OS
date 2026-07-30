"""Add managed per-record encrypted credential envelopes.

Revision ID: 0011_h1_envelopes
Revises: 0010_h1_authorization
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_h1_envelopes"
down_revision: str | Sequence[str] | None = "0010_h1_authorization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREDENTIAL_TABLES = ("gmail_credentials", "calendar_credentials", "drive_credentials")


def _enable_workspace_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table_name}_workspace_isolation ON {table_name}
        USING (
            workspace_id = NULLIF(
                current_setting('atlas.workspace_id', TRUE), ''
            )::UUID
        )
        WITH CHECK (
            workspace_id = NULLIF(
                current_setting('atlas.workspace_id', TRUE), ''
            )::UUID
        )
        """
    )


def _add_credential_shadow_columns(table_name: str) -> None:
    op.add_column(table_name, sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.add_column(table_name, sa.Column("envelope_id", sa.Uuid(), nullable=True))
    op.add_column(
        table_name,
        sa.Column("envelope_legacy_checksum", sa.String(length=64), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column(
            "envelope_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "envelope_cutover",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "reauthorization_required",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.execute(
        f"""
        UPDATE {table_name} AS credential
        SET workspace_id = (
            SELECT membership.workspace_id
            FROM workspace_memberships AS membership
            WHERE membership.user_id = credential.user_id
              AND membership.status = 'active'
            ORDER BY
              CASE membership.role_key
                WHEN 'workspace_owner' THEN 0
                WHEN 'workspace_admin' THEN 1
                ELSE 2
              END,
              membership.workspace_id::TEXT
            LIMIT 1
        )
        """
    )
    op.execute(
        f"""
        UPDATE {table_name}
        SET reauthorization_required = TRUE
        WHERE workspace_id IS NULL
        """
    )


def upgrade() -> None:
    op.create_table(
        "encrypted_envelopes",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=96), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("format_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("kms_key_resource", sa.Text(), nullable=False),
        sa.Column("kms_key_version", sa.String(length=128), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("rotation_request_id", sa.Uuid(), nullable=True),
        sa.Column("legacy_source", sa.String(length=64), nullable=True),
        sa.Column("legacy_checksum", sa.String(length=64), nullable=True),
        sa.Column(
            "shadow_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cutover_complete",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "encrypted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quarantine_reason", sa.String(length=96), nullable=True),
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
            "status IN ('active', 'rotating', 'quarantined', 'disabled')",
            name="ck_encrypted_envelopes_status",
        ),
        sa.CheckConstraint(
            "generation > 0",
            name="ck_encrypted_envelopes_generation",
        ),
        sa.CheckConstraint(
            "format_version > 0",
            name="ck_encrypted_envelopes_format_version",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_encrypted_envelopes_workspace",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_encrypted_envelopes",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "record_type",
            "record_id",
            name="uq_encrypted_envelopes_record",
        ),
    )
    op.create_index(
        "ix_encrypted_envelopes_rotation",
        "encrypted_envelopes",
        [
            "workspace_id",
            "status",
            "kms_key_resource",
            "kms_key_version",
        ],
    )
    _enable_workspace_rls("encrypted_envelopes")

    for table_name in CREDENTIAL_TABLES:
        _add_credential_shadow_columns(table_name)
        op.create_foreign_key(
            f"fk_{table_name}_envelope",
            table_name,
            "encrypted_envelopes",
            ["workspace_id", "envelope_id"],
            ["workspace_id", "id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM encrypted_envelopes)
               OR EXISTS (
                    SELECT 1 FROM gmail_credentials
                    WHERE envelope_id IS NOT NULL
                       OR envelope_legacy_checksum IS NOT NULL
                       OR envelope_verified_at IS NOT NULL
                       OR envelope_cutover
               )
               OR EXISTS (
                    SELECT 1 FROM calendar_credentials
                    WHERE envelope_id IS NOT NULL
                       OR envelope_legacy_checksum IS NOT NULL
                       OR envelope_verified_at IS NOT NULL
                       OR envelope_cutover
               )
               OR EXISTS (
                    SELECT 1 FROM drive_credentials
                    WHERE envelope_id IS NOT NULL
                       OR envelope_legacy_checksum IS NOT NULL
                       OR envelope_verified_at IS NOT NULL
                       OR envelope_cutover
               )
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H1-07 with envelope migration state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    for table_name in reversed(CREDENTIAL_TABLES):
        op.drop_constraint(
            f"fk_{table_name}_envelope",
            table_name,
            type_="foreignkey",
        )
        for column_name in (
            "reauthorization_required",
            "envelope_cutover",
            "envelope_verified_at",
            "envelope_legacy_checksum",
            "envelope_id",
            "workspace_id",
        ):
            op.drop_column(table_name, column_name)
    op.drop_index(
        "ix_encrypted_envelopes_rotation",
        table_name="encrypted_envelopes",
    )
    op.drop_table("encrypted_envelopes")
