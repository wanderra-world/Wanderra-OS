"""Add encrypted Google Drive OAuth credentials and file metadata."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_add_drive_integration"
down_revision = "0004_add_calendar_integration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drive_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "drive_oauth_states",
        sa.Column("state", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_verifier", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state"),
    )
    op.create_index("ix_drive_oauth_states_user_id", "drive_oauth_states", ["user_id"])
    op.create_table(
        "drive_file_metadata",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("web_view_link", sa.Text(), nullable=True),
        sa.Column("md5_checksum", sa.String(length=64), nullable=True),
        sa.Column("parents", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "file_id"),
    )
    op.create_index(
        "ix_drive_file_metadata_user_name",
        "drive_file_metadata",
        ["user_id", "name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_drive_file_metadata_user_name", table_name="drive_file_metadata"
    )
    op.drop_table("drive_file_metadata")
    op.drop_index("ix_drive_oauth_states_user_id", table_name="drive_oauth_states")
    op.drop_table("drive_oauth_states")
    op.drop_table("drive_credentials")
