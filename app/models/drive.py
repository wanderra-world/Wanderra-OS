import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DriveCredential(Base):
    __tablename__ = "drive_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "envelope_id"],
            ["encrypted_envelopes.workspace_id", "encrypted_envelopes.id"],
            ondelete="RESTRICT",
            name="fk_drive_credentials_envelope",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_payload: Mapped[str] = mapped_column(Text)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    envelope_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    envelope_legacy_checksum: Mapped[str | None] = mapped_column(String(64))
    envelope_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    envelope_cutover: Mapped[bool] = mapped_column(Boolean, server_default="false")
    reauthorization_required: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DriveOAuthState(Base):
    __tablename__ = "drive_oauth_states"

    state: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_verifier: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DriveFileMetadata(Base):
    __tablename__ = "drive_file_metadata"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(255))
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    web_view_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    md5_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parents: Mapped[list[str]] = mapped_column(JSONB, default=list)
    metadata_payload: Mapped[dict] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
