"""Add encrypted Google Calendar OAuth credentials and state."""

from alembic import op
import sqlalchemy as sa

revision = "0004_add_calendar_integration"
down_revision = "0003_store_gmail_pkce_verifier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_credentials",
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
        "calendar_oauth_states",
        sa.Column("state", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_verifier", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state"),
    )
    op.create_index(
        "ix_calendar_oauth_states_user_id", "calendar_oauth_states", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calendar_oauth_states_user_id", table_name="calendar_oauth_states"
    )
    op.drop_table("calendar_oauth_states")
    op.drop_table("calendar_credentials")
