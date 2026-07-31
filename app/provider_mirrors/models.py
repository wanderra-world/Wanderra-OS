"""Workspace-owned H2-04 provider mirror persistence."""

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
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ProviderMirror(Base):
    __tablename__ = "provider_mirrors"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_provider_mirrors"),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_provider_mirrors_connection",
        ),
        UniqueConstraint(
            "workspace_id",
            "connection_id",
            "resource_type",
            "external_id",
            name="uq_provider_mirrors_external_identity",
        ),
        CheckConstraint("version > 0", name="ck_provider_mirrors_version"),
        CheckConstraint(
            "authority IN ('provider_authoritative', 'atlas_authoritative', "
            "'user_resolved', 'mergeable')",
            name="ck_provider_mirrors_authority",
        ),
        CheckConstraint(
            "sync_state IN ('synced', 'conflict', 'tombstoned', 'deleted')",
            name="ck_provider_mirrors_sync_state",
        ),
        Index(
            "ix_provider_mirrors_state",
            "workspace_id",
            "connection_id",
            "sync_state",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_type: Mapped[str] = mapped_column(String(96))
    external_id: Mapped[str] = mapped_column(String(1024))
    provider_version: Mapped[str] = mapped_column(String(512))
    etag: Mapped[str | None] = mapped_column(String(512))
    provider_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    normalized_hash: Mapped[str] = mapped_column(String(64))
    raw_payload_reference: Mapped[str | None] = mapped_column(Text)
    raw_payload_owner: Mapped[str | None] = mapped_column(String(96))
    authority: Mapped[str] = mapped_column(String(32))
    field_authority: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    sync_state: Mapped[str] = mapped_column(String(32))
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProviderExternalReference(Base):
    __tablename__ = "provider_external_references"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_provider_external_references"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "mirror_id"],
            ["provider_mirrors.workspace_id", "provider_mirrors.id"],
            ondelete="RESTRICT",
            name="fk_provider_external_references_mirror",
        ),
        UniqueConstraint(
            "workspace_id",
            "connection_id",
            "resource_type",
            "external_id",
            name="uq_provider_external_references_identity",
        ),
        UniqueConstraint(
            "workspace_id", "mirror_id", name="uq_provider_external_references_mirror"
        ),
        CheckConstraint(
            "version > 0", name="ck_provider_external_references_version"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    mirror_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_type: Mapped[str] = mapped_column(String(96))
    external_id: Mapped[str] = mapped_column(String(1024))
    canonical_reference_type: Mapped[str | None] = mapped_column(String(96))
    canonical_reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approval_reference: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProviderMirrorConflict(Base):
    __tablename__ = "provider_mirror_conflicts"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_provider_mirror_conflicts"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "mirror_id"],
            ["provider_mirrors.workspace_id", "provider_mirrors.id"],
            ondelete="RESTRICT",
            name="fk_provider_mirror_conflicts_mirror",
        ),
        CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_provider_mirror_conflicts_status",
        ),
        CheckConstraint(
            "version > 0", name="ck_provider_mirror_conflicts_version"
        ),
        Index(
            "uq_provider_mirror_conflicts_open",
            "workspace_id",
            "mirror_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    mirror_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(96))
    atlas_hash: Mapped[str] = mapped_column(String(64))
    provider_hash: Mapped[str] = mapped_column(String(64))
    provider_version: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32))
    resolution: Mapped[str | None] = mapped_column(String(32))
    resolution_hash: Mapped[str | None] = mapped_column(String(64))
    resolution_idempotency_key: Mapped[str | None] = mapped_column(String(128))
    resolution_request_digest: Mapped[str | None] = mapped_column(String(64))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class ProviderMirrorComparison(Base):
    __tablename__ = "provider_mirror_comparisons"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_provider_mirror_comparisons"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "mirror_id"],
            ["provider_mirrors.workspace_id", "provider_mirrors.id"],
            ondelete="RESTRICT",
            name="fk_provider_mirror_comparisons_mirror",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_provider_mirror_comparisons_idempotency",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    mirror_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    direction: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(32))
    conflict_reason: Mapped[str | None] = mapped_column(String(96))
    observed_provider_version: Mapped[str] = mapped_column(String(512))
    observed_hash: Mapped[str] = mapped_column(String(64))
    mirror_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
