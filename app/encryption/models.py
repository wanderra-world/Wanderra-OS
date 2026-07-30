"""Tenant-owned persistence for managed encrypted credential envelopes."""

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
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class EncryptedEnvelope(Base):
    """One independently encrypted credential record and rotation checkpoint."""

    __tablename__ = "encrypted_envelopes"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_encrypted_envelopes"),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_encrypted_envelopes_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "record_type",
            "record_id",
            name="uq_encrypted_envelopes_record",
        ),
        CheckConstraint(
            "status IN ('active', 'rotating', 'quarantined', 'disabled')",
            name="ck_encrypted_envelopes_status",
        ),
        CheckConstraint("generation > 0", name="ck_encrypted_envelopes_generation"),
        CheckConstraint(
            "format_version > 0",
            name="ck_encrypted_envelopes_format_version",
        ),
        Index(
            "ix_encrypted_envelopes_rotation",
            "workspace_id",
            "status",
            "kms_key_resource",
            "kms_key_version",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    record_type: Mapped[str] = mapped_column(String(96))
    record_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    format_version: Mapped[int] = mapped_column(Integer, server_default="1")
    algorithm: Mapped[str] = mapped_column(String(32))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    kms_key_resource: Mapped[str] = mapped_column(Text)
    kms_key_version: Mapped[str] = mapped_column(String(128))
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    generation: Mapped[int] = mapped_column(Integer, server_default="1")
    rotation_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    legacy_source: Mapped[str | None] = mapped_column(String(64))
    legacy_checksum: Mapped[str | None] = mapped_column(String(64))
    shadow_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cutover_complete: Mapped[bool] = mapped_column(Boolean, server_default="false")
    encrypted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quarantined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    quarantine_reason: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
