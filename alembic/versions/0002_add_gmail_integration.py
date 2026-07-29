"""Add encrypted Gmail OAuth credentials and external-memory identity."""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_gmail_integration"
down_revision = "0001_create_memory_tables"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("conversation_messages", sa.Column("source", sa.String(64), nullable=True))
    op.add_column("conversation_messages", sa.Column("external_id", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_memory_message_source_external_id", "conversation_messages", ["source", "external_id"])
    op.create_table("gmail_credentials", sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("encrypted_payload", sa.Text(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("user_id"))
    op.create_table("gmail_oauth_states", sa.Column("state", sa.String(255), nullable=False), sa.Column("user_id", sa.Uuid(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("state"))
    op.create_index("ix_gmail_oauth_states_user_id", "gmail_oauth_states", ["user_id"])

def downgrade() -> None:
    op.drop_index("ix_gmail_oauth_states_user_id", table_name="gmail_oauth_states")
    op.drop_table("gmail_oauth_states"); op.drop_table("gmail_credentials")
    op.drop_constraint("uq_memory_message_source_external_id", "conversation_messages", type_="unique")
    op.drop_column("conversation_messages", "external_id"); op.drop_column("conversation_messages", "source")
