"""Tenant-owned H2-09 backfill and cutover evidence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ConnectionBackfillEvidence(Base):
    __tablename__ = "connection_backfill_evidence"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "source_system",
            "source_record_id",
            name="pk_connection_backfill_evidence",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_connection_backfill_evidence_connection",
        ),
        CheckConstraint(
            "status IN ('mapped','reauthorization_required')",
            name="ck_connection_backfill_evidence_status",
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_system: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[str] = mapped_column(String(255))
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_checksum: Mapped[str] = mapped_column(String(64))
    evidence_checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="1")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CapabilityCutoverEvidence(Base):
    __tablename__ = "capability_cutover_evidence"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_capability_cutover_evidence"),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_capability_cutover_evidence_connection",
        ),
        CheckConstraint(
            "capability IN ('email','calendar','storage')",
            name="ck_capability_cutover_evidence_capability",
        ),
        CheckConstraint(
            "route_kind IN ('read','mutation')", name="ck_capability_cutover_evidence_route_kind"
        ),
        CheckConstraint(
            "requested_route IN ('legacy','shadow','canonical')",
            name="ck_capability_cutover_evidence_route",
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    capability: Mapped[str] = mapped_column(String(16))
    route_kind: Mapped[str] = mapped_column(String(16))
    requested_route: Mapped[str] = mapped_column(String(16))
    samples: Mapped[int] = mapped_column(Integer)
    matches: Mapped[int] = mapped_column(Integer)
    minimum_samples: Mapped[int] = mapped_column(Integer)
    maximum_mismatch_rate: Mapped[str] = mapped_column(String(32))
    approved: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
