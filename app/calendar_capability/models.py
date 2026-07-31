"""Tenant-owned Calendar routing and immutable shadow evidence."""

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


class CalendarCapabilityRoute(Base):
    __tablename__ = "calendar_capability_routes"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "connection_id",
            name="pk_calendar_capability_routes",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_calendar_capability_routes_connection",
        ),
        CheckConstraint(
            "route IN ('legacy', 'shadow', 'canonical')",
            name="ck_calendar_capability_routes_route",
        ),
        CheckConstraint(
            "version > 0", name="ck_calendar_capability_routes_version"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    route: Mapped[str] = mapped_column(String(16), server_default="legacy")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CalendarShadowComparison(Base):
    __tablename__ = "calendar_shadow_comparisons"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id", "id", name="pk_calendar_shadow_comparisons"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_calendar_shadow_comparisons_connection",
        ),
        CheckConstraint(
            "operation = 'list'",
            name="ck_calendar_shadow_comparisons_operation",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    correlation_id: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(16))
    equivalent: Mapped[bool] = mapped_column(Boolean)
    compared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
