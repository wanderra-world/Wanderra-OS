"""Workspace-owned, single-use H2-03 OAuth transaction metadata."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class OAuthTransaction(Base):
    """Secret-free OAuth lifecycle metadata; sensitive material is enveloped."""

    __tablename__ = "oauth_transactions"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_oauth_transactions"),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id", "provider_key"],
            ["connections.workspace_id", "connections.id", "connections.provider_key"],
            ondelete="RESTRICT",
            name="fk_oauth_transactions_connection_provider",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "secret_envelope_id"],
            ["encrypted_envelopes.workspace_id", "encrypted_envelopes.id"],
            ondelete="RESTRICT",
            name="fk_oauth_transactions_envelope",
        ),
        UniqueConstraint(
            "workspace_id", "state_digest", name="uq_oauth_transactions_state"
        ),
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_oauth_transactions_idempotency"
        ),
        CheckConstraint("version > 0", name="ck_oauth_transactions_version"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled', 'failed', 'expired')",
            name="ck_oauth_transactions_status",
        ),
        Index("ix_oauth_transactions_status", "workspace_id", "status", "expires_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider_key: Mapped[str] = mapped_column(String(96))
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    membership_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    authorization_decision_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    secret_envelope_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(String(32))
    state_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    issuer: Mapped[str] = mapped_column(String(512))
    requested_capabilities: Mapped[list[str]] = mapped_column(JSONB)
    requested_scopes: Mapped[list[str]] = mapped_column(JSONB)
    required_scopes: Mapped[list[str]] = mapped_column(JSONB)
    returned_scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    incremental: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(32))
    failure_code: Mapped[str | None] = mapped_column(String(96))
    credential_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    correlation_id: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
