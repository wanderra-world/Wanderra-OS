"""Persistence models for the H2-01 connection foundation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ProviderRegistryEntry(Base):
    """Stable provider identifier and non-operational family metadata."""

    __tablename__ = "provider_registry"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_provider_registry_version"),
        PrimaryKeyConstraint(
            "provider_key",
            "version",
            name="pk_provider_registry",
        ),
    )

    provider_key: Mapped[str] = mapped_column(String(96))
    version: Mapped[int] = mapped_column(Integer)
    provider_family: Mapped[str] = mapped_column(String(96))
    display_name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConnectionKind(Base):
    """Versioned provider-neutral connection-kind definition."""

    __tablename__ = "connection_kinds"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_connection_kinds_version"),
        PrimaryKeyConstraint(
            "kind_key",
            "version",
            name="pk_connection_kinds",
        ),
    )

    kind_key: Mapped[str] = mapped_column(String(96))
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProviderCapability(Base):
    """Versioned capability identifier; execution ports belong to H2-05."""

    __tablename__ = "provider_capabilities"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_provider_capabilities_version"),
        PrimaryKeyConstraint(
            "capability_key",
            "version",
            name="pk_provider_capabilities",
        ),
    )

    capability_key: Mapped[str] = mapped_column(String(96))
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConnectionKindCapability(Base):
    """Capabilities permitted by one versioned connection kind."""

    __tablename__ = "connection_kind_capabilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["kind_key", "kind_version"],
            ["connection_kinds.kind_key", "connection_kinds.version"],
            ondelete="RESTRICT",
            name="fk_connection_kind_capabilities_kind",
        ),
        ForeignKeyConstraint(
            ["capability_key", "capability_version"],
            ["provider_capabilities.capability_key", "provider_capabilities.version"],
            ondelete="RESTRICT",
            name="fk_connection_kind_capabilities_capability",
        ),
        PrimaryKeyConstraint(
            "kind_key",
            "kind_version",
            "capability_key",
            "capability_version",
            name="pk_connection_kind_capabilities",
        ),
    )

    kind_key: Mapped[str] = mapped_column(String(96))
    kind_version: Mapped[int] = mapped_column(Integer)
    capability_key: Mapped[str] = mapped_column(String(96))
    capability_version: Mapped[int] = mapped_column(Integer)


class Connection(Base):
    """Canonical workspace-owned provider account connection."""

    __tablename__ = "connections"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_connections"),
        ForeignKeyConstraint(
            ["workspace_id", "organization_id", "cell_id"],
            [
                "workspaces.workspace_id",
                "workspaces.organization_id",
                "workspaces.cell_id",
            ],
            ondelete="RESTRICT",
            name="fk_connections_workspace_placement",
        ),
        ForeignKeyConstraint(
            ["provider_key", "provider_version"],
            ["provider_registry.provider_key", "provider_registry.version"],
            ondelete="RESTRICT",
            name="fk_connections_provider",
        ),
        ForeignKeyConstraint(
            ["connection_kind", "connection_kind_version"],
            ["connection_kinds.kind_key", "connection_kinds.version"],
            ondelete="RESTRICT",
            name="fk_connections_kind",
        ),
        UniqueConstraint(
            "workspace_id",
            "provider_key",
            "connection_kind",
            "provider_account_id",
            name="uq_connections_workspace_provider_kind_account",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "connection_kind",
            "connection_kind_version",
            name="uq_connections_id_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'degraded', "
            "'reauthorization_required', 'revoked', 'closed')",
            name="ck_connections_status",
        ),
        CheckConstraint("version > 0", name="ck_connections_version"),
        CheckConstraint(
            """
            (status = 'pending'
                AND activated_at IS NULL
                AND revoked_at IS NULL
                AND closed_at IS NULL)
            OR (status IN ('active', 'degraded')
                AND activated_at IS NOT NULL
                AND revoked_at IS NULL
                AND closed_at IS NULL)
            OR (status = 'reauthorization_required'
                AND revoked_at IS NULL
                AND closed_at IS NULL)
            OR (status = 'revoked'
                AND revoked_at IS NOT NULL
                AND closed_at IS NULL)
            OR (status = 'closed' AND closed_at IS NOT NULL)
            """,
            name="ck_connections_lifecycle_evidence",
        ),
        Index("ix_connections_workspace_status", "workspace_id", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider_key: Mapped[str] = mapped_column(String(96))
    provider_version: Mapped[int] = mapped_column(Integer, server_default="1")
    connection_kind: Mapped[str] = mapped_column(String(96))
    connection_kind_version: Mapped[int] = mapped_column(
        Integer, server_default="1"
    )
    provider_account_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    granted_scopes: Mapped[list[str]] = mapped_column(
        JSONB, server_default="[]", default=list
    )
    status: Mapped[str] = mapped_column(String(32), server_default="pending")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    last_material_actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    degraded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reauthorization_required_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConnectionCapabilityGrant(Base):
    """Workspace-owned capability grant on one canonical connection."""

    __tablename__ = "connection_capability_grants"
    __table_args__ = (
        PrimaryKeyConstraint(
            "workspace_id",
            "connection_id",
            "capability_key",
            "capability_version",
            name="pk_connection_capability_grants",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "connection_id",
                "connection_kind",
                "connection_kind_version",
            ],
            [
                "connections.workspace_id",
                "connections.id",
                "connections.connection_kind",
                "connections.connection_kind_version",
            ],
            ondelete="CASCADE",
            name="fk_connection_capability_grants_connection",
        ),
        ForeignKeyConstraint(
            [
                "connection_kind",
                "connection_kind_version",
                "capability_key",
                "capability_version",
            ],
            [
                "connection_kind_capabilities.kind_key",
                "connection_kind_capabilities.kind_version",
                "connection_kind_capabilities.capability_key",
                "connection_kind_capabilities.capability_version",
            ],
            ondelete="RESTRICT",
            name="fk_connection_capability_grants_allowed",
        ),
        CheckConstraint(
            "status IN ('granted', 'revoked')",
            name="ck_connection_capability_grants_status",
        ),
        CheckConstraint(
            "(status = 'granted' AND revoked_at IS NULL) "
            "OR (status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_connection_capability_grants_lifecycle",
        ),
        Index(
            "ix_connection_capability_grants_effective",
            "workspace_id",
            "connection_id",
            "status",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_kind: Mapped[str] = mapped_column(String(96))
    connection_kind_version: Mapped[int] = mapped_column(Integer)
    capability_key: Mapped[str] = mapped_column(String(96))
    capability_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), server_default="granted")
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
