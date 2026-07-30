"""Workspace-owned H2-02 credential and migration metadata."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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


class ConnectionCredential(Base):
    """Metadata for one independently encrypted connection credential generation."""

    __tablename__ = "connection_credentials"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_connection_credentials"),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id", "provider_key"],
            ["connections.workspace_id", "connections.id", "connections.provider_key"],
            ondelete="RESTRICT",
            name="fk_connection_credentials_connection_provider",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "envelope_id"],
            ["encrypted_envelopes.workspace_id", "encrypted_envelopes.id"],
            ondelete="RESTRICT",
            name="fk_connection_credentials_envelope",
        ),
        UniqueConstraint(
            "workspace_id",
            "connection_id",
            "credential_kind",
            "generation",
            name="uq_connection_credentials_generation",
        ),
        CheckConstraint("generation > 0", name="ck_connection_credentials_generation"),
        CheckConstraint("version > 0", name="ck_connection_credentials_version"),
        CheckConstraint(
            "status IN ('shadow_verified', 'active', "
            "'reauthorization_required', 'revoked', 'disabled')",
            name="ck_connection_credentials_status",
        ),
        Index(
            "ix_connection_credentials_current",
            "workspace_id",
            "connection_id",
            "credential_kind",
            "status",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider_key: Mapped[str] = mapped_column(String(96))
    credential_kind: Mapped[str] = mapped_column(String(96))
    generation: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    envelope_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(32))
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    source_system: Mapped[str | None] = mapped_column(String(96))
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    source_checksum: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CredentialMigrationInventory(Base):
    """Idempotent, resumable evidence for one legacy credential row."""

    __tablename__ = "credential_migration_inventory"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_credential_migration_inventory"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_credential_migration_inventory_connection",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "credential_id"],
            ["connection_credentials.workspace_id", "connection_credentials.id"],
            ondelete="RESTRICT",
            name="fk_credential_migration_inventory_credential",
        ),
        UniqueConstraint(
            "workspace_id",
            "source_system",
            "source_record_id",
            name="uq_credential_migration_inventory_source",
        ),
        CheckConstraint(
            "status IN ('eligible', 'migrated', 'verified', "
            "'reauthorization_required', 'failed')",
            name="ck_credential_migration_inventory_status",
        ),
        Index(
            "ix_credential_migration_inventory_status",
            "workspace_id",
            "status",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_system: Mapped[str] = mapped_column(String(96))
    source_record_id: Mapped[str] = mapped_column(String(255))
    source_checksum: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(String(32))
    exception_code: Mapped[str | None] = mapped_column(String(96))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
