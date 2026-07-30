"""Add H2-03 single-use OAuth transaction custody.

Revision ID: 0016_h2_oauth_transactions
Revises: 0015_h2_credentials
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_h2_oauth_transactions"
down_revision: str | Sequence[str] | None = "0015_h2_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_transactions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(96), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_decision_id", sa.Uuid(), nullable=False),
        sa.Column("secret_envelope_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("state_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("requested_capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("requested_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("required_scopes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "returned_scopes",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("incremental", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(96), nullable=True),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_oauth_transactions"),
        sa.UniqueConstraint(
            "workspace_id", "state_digest", name="uq_oauth_transactions_state"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_oauth_transactions_idempotency",
        ),
        sa.CheckConstraint("version > 0", name="ck_oauth_transactions_version"),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled', 'failed', 'expired')",
            name="ck_oauth_transactions_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id", "provider_key"],
            ["connections.workspace_id", "connections.id", "connections.provider_key"],
            ondelete="RESTRICT",
            name="fk_oauth_transactions_connection_provider",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "secret_envelope_id"],
            ["encrypted_envelopes.workspace_id", "encrypted_envelopes.id"],
            ondelete="RESTRICT",
            name="fk_oauth_transactions_envelope",
        ),
    )
    op.create_index(
        "ix_oauth_transactions_status",
        "oauth_transactions",
        ["workspace_id", "status", "expires_at"],
    )
    op.execute("ALTER TABLE oauth_transactions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE oauth_transactions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY oauth_transactions_workspace_isolation ON oauth_transactions
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
    op.execute(
        """
        CREATE TRIGGER oauth_transactions_workspace_writable
        BEFORE INSERT OR UPDATE OR DELETE ON oauth_transactions
        FOR EACH ROW EXECUTE FUNCTION enforce_workspace_write_state()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_oauth_transaction_context()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            envelope_connection UUID;
            envelope_record UUID;
            envelope_type TEXT;
            expected_type TEXT;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.workspace_id, NEW.id, NEW.connection_id, NEW.provider_key,
                    NEW.actor_id, NEW.session_id, NEW.membership_id,
                    NEW.authorization_decision_id, NEW.secret_envelope_id,
                    NEW.purpose, NEW.state_digest, NEW.request_digest,
                    NEW.idempotency_key, NEW.redirect_uri, NEW.issuer,
                    NEW.requested_capabilities, NEW.requested_scopes,
                    NEW.required_scopes, NEW.incremental, NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.workspace_id, OLD.id, OLD.connection_id, OLD.provider_key,
                    OLD.actor_id, OLD.session_id, OLD.membership_id,
                    OLD.authorization_decision_id, OLD.secret_envelope_id,
                    OLD.purpose, OLD.state_digest, OLD.request_digest,
                    OLD.idempotency_key, OLD.redirect_uri, OLD.issuer,
                    OLD.requested_capabilities, OLD.requested_scopes,
                    OLD.required_scopes, OLD.incremental, OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'OAuth transaction binding is immutable';
                END IF;
                IF OLD.status <> 'pending' THEN
                    RAISE EXCEPTION 'OAuth terminal transaction is immutable';
                END IF;
                IF NEW.status NOT IN ('completed', 'cancelled', 'failed', 'expired')
                   OR NEW.version <> OLD.version + 1
                THEN
                    RAISE EXCEPTION 'OAuth transition is invalid';
                END IF;
            END IF;
            SELECT connection_id, record_id, record_type
              INTO envelope_connection, envelope_record, envelope_type
              FROM encrypted_envelopes
             WHERE workspace_id = NEW.workspace_id
               AND id = NEW.secret_envelope_id;
            expected_type := 'oauth_transaction_secret:' || NEW.provider_key ||
                ':' || NEW.purpose;
            IF envelope_connection IS DISTINCT FROM NEW.connection_id
               OR envelope_record IS DISTINCT FROM NEW.id
               OR envelope_type IS DISTINCT FROM expected_type
            THEN
                RAISE EXCEPTION 'OAuth envelope context mismatch';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER oauth_transactions_enforce_context
        BEFORE INSERT OR UPDATE ON oauth_transactions
        FOR EACH ROW EXECUTE FUNCTION enforce_oauth_transaction_context()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM oauth_transactions)
            THEN
                RAISE EXCEPTION
                    'cannot downgrade H2-03 with OAuth transaction state; '
                    'use a reviewed forward fix';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER oauth_transactions_enforce_context ON oauth_transactions"
    )
    op.execute("DROP FUNCTION enforce_oauth_transaction_context()")
    op.execute(
        "DROP TRIGGER oauth_transactions_workspace_writable ON oauth_transactions"
    )
    op.drop_table("oauth_transactions")
