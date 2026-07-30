"""Tenant-owned H1-08 command and event-processing state."""

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


class AuditChainHead(Base):
    __tablename__ = "audit_chain_heads"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", name="pk_audit_chain_heads"),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_audit_chain_heads_workspace",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    last_sequence: Mapped[int] = mapped_column(server_default="0")
    last_digest: Mapped[str] = mapped_column(String(64), server_default="")
    verified_sequence: Mapped[int] = mapped_column(server_default="0")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CommandIdempotency(Base):
    __tablename__ = "command_idempotency"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "actor_id",
            "command_type",
            "idempotency_key",
            name="pk_command_idempotency",
        ),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_command_idempotency_workspace",
        ),
        CheckConstraint(
            "status IN ('started', 'completed')",
            name="ck_command_idempotency_status",
        ),
        Index(
            "ix_command_idempotency_retention",
            "workspace_id",
            "retention_until",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    command_type: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), server_default="started")
    outcome_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    aggregate_version: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AggregateVersion(Base):
    __tablename__ = "aggregate_versions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "aggregate_type",
            "aggregate_id",
            name="pk_aggregate_versions",
        ),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_aggregate_versions_workspace",
        ),
        CheckConstraint("version >= 0", name="ck_aggregate_versions_version"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    aggregate_type: Mapped[str] = mapped_column(String(96))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InboxEvent(Base):
    __tablename__ = "inbox_events"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "consumer_id",
            "event_id",
            name="pk_inbox_events",
        ),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_inbox_events_workspace",
        ),
        CheckConstraint(
            "status IN ('processed', 'quarantined')",
            name="ck_inbox_events_status",
        ),
        Index(
            "ix_inbox_events_retention",
            "workspace_id",
            "retention_until",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    consumer_id: Mapped[str] = mapped_column(String(128))
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(128))
    schema_major: Mapped[int] = mapped_column(Integer)
    schema_minor: Mapped[int] = mapped_column(Integer)
    aggregate_type: Mapped[str] = mapped_column(String(96))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    aggregate_sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    payload_digest: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConsumerSequence(Base):
    __tablename__ = "consumer_sequences"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "consumer_id",
            "aggregate_type",
            "aggregate_id",
            name="pk_consumer_sequences",
        ),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_consumer_sequences_workspace",
        ),
        CheckConstraint(
            "last_sequence >= 0",
            name="ck_consumer_sequences_last_sequence",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    consumer_id: Mapped[str] = mapped_column(String(128))
    aggregate_type: Mapped[str] = mapped_column(String(96))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    last_sequence: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EventQuarantine(Base):
    __tablename__ = "event_quarantine"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_event_quarantine"),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_event_quarantine_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "consumer_id",
            "event_id",
            name="uq_event_quarantine_consumer_event",
        ),
        CheckConstraint(
            "status IN ('quarantined', 'replayed')",
            name="ck_event_quarantine_status",
        ),
        Index(
            "ix_event_quarantine_status",
            "workspace_id",
            "status",
            "quarantined_at",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    consumer_id: Mapped[str] = mapped_column(String(128))
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(96))
    expected_sequence: Mapped[int | None] = mapped_column(Integer)
    observed_sequence: Mapped[int | None] = mapped_column(Integer)
    event_payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    payload_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), server_default="quarantined")
    quarantined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replayed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    replay_decision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
