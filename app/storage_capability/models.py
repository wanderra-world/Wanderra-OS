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


class StorageCapabilityRoute(Base):
    __tablename__ = "storage_capability_routes"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "connection_id", name="pk_storage_capability_routes"),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_storage_capability_routes_connection",
        ),
        CheckConstraint(
            "route IN ('legacy', 'shadow', 'canonical')", name="ck_storage_capability_routes_route"
        ),
        CheckConstraint("version > 0", name="ck_storage_capability_routes_version"),
        CheckConstraint(
            "mutation_route IN ('legacy', 'canonical')",
            name="ck_storage_capability_routes_mutation_route",
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    route: Mapped[str] = mapped_column(String(16), server_default="legacy")
    mutation_route: Mapped[str] = mapped_column(String(16), server_default="legacy")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StorageShadowComparison(Base):
    __tablename__ = "storage_shadow_comparisons"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_storage_shadow_comparisons"),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["connections.workspace_id", "connections.id"],
            ondelete="RESTRICT",
            name="fk_storage_shadow_comparisons_connection",
        ),
        CheckConstraint(
            "operation IN ('list','search','metadata','download','read_text')",
            name="ck_storage_shadow_comparisons_operation",
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
