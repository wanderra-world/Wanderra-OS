"""Persist the Gmail OAuth PKCE verifier for the callback exchange."""

from alembic import op
import sqlalchemy as sa

revision = "0003_store_gmail_pkce_verifier"
down_revision = "0002_add_gmail_integration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gmail_oauth_states", sa.Column("code_verifier", sa.String(length=255), nullable=True))
    op.execute("DELETE FROM gmail_oauth_states")
    op.alter_column("gmail_oauth_states", "code_verifier", nullable=False)


def downgrade() -> None:
    op.drop_column("gmail_oauth_states", "code_verifier")
