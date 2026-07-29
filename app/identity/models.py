"""Persistence models for canonical users and external login identities."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.memory import Conversation, Project


class User(Base):
    """Global human identity that owns no tenant data directly."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'disabled')",
            name="ck_users_status",
        ),
        CheckConstraint("version > 0", name="ck_users_positive_version"),
        CheckConstraint(
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
            name="ck_users_email_verification_provenance",
        ),
        Index("ix_users_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verification_source: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    external_identities: Mapped[list[ExternalIdentityLink]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    projects: Mapped[list[Project]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class ExternalIdentityLink(Base):
    """Login-provider identity linked by immutable issuer and subject."""

    __tablename__ = "external_identity_links"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'review_pending', 'revoked')",
            name="ck_external_identity_links_status",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_external_identity_links_positive_version",
        ),
        CheckConstraint(
            "btrim(issuer) <> '' AND btrim(subject) <> ''",
            name="ck_external_identity_links_issuer_subject_present",
        ),
        CheckConstraint(
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
        UniqueConstraint(
            "issuer",
            "subject",
            name="uq_external_identity_links_issuer_subject",
        ),
        Index("ix_external_identity_links_user_id", "user_id"),
        Index("ix_external_identity_links_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verification_source: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="external_identities")
