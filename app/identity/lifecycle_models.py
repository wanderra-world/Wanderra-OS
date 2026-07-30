"""Persistence models for the H1-03 revocable identity lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.identity.models import User


class IdentitySession(Base):
    """Opaque, hashed, server-side session scoped to one workspace."""

    __tablename__ = "identity_sessions"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_identity_sessions"),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_identity_sessions_workspace",
        ),
        CheckConstraint(
            "authentication_strength IN ('oidc', 'password', 'mfa')",
            name="ck_identity_sessions_authentication_strength",
        ),
        UniqueConstraint("token_hash", name="uq_identity_sessions_token_hash"),
        Index("ix_identity_sessions_user_active", "user_id", "revoked_at", "expires_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    device_id: Mapped[str] = mapped_column(String(255))
    authentication_strength: Mapped[str] = mapped_column(String(32))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mfa_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="sessions")


class IdentityLifecycleToken(Base):
    """Hashed, scoped, expiring, single-use invitation or recovery token."""

    __tablename__ = "identity_lifecycle_tokens"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_identity_lifecycle_tokens",
        ),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_identity_lifecycle_tokens_workspace",
        ),
        CheckConstraint(
            "purpose IN ('invitation', 'recovery')",
            name="ck_identity_lifecycle_tokens_purpose",
        ),
        UniqueConstraint("token_hash", name="uq_identity_lifecycle_tokens_token_hash"),
        Index(
            "ix_identity_lifecycle_tokens_user_purpose",
            "user_id",
            "purpose",
            "consumed_at",
            "revoked_at",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    purpose: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64))
    scope: Mapped[dict[str, object]] = mapped_column(JSONB)
    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SecurityNotification(Base):
    """Redacted durable notification emitted for identity security events."""

    __tablename__ = "security_notifications"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_security_notifications",
        ),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_security_notifications_workspace",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_security_notifications_status",
        ),
        Index("ix_security_notifications_pending", "status", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(128))
    destination_hint: Mapped[str | None] = mapped_column(String(320))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
