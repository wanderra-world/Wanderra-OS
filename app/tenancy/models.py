"""Persistence models for the H1 organization and workspace foundation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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


class Cell(Base):
    """Physical placement target for one or more workspaces."""

    __tablename__ = "cells"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    region: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Organization(Base):
    """Mandatory legal and administrative owner of workspaces."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "organization_type IN ('business', 'personal')",
            name="ck_organizations_type",
        ),
        CheckConstraint(
            "status IN ('active', 'closing', 'closed')",
            name="ck_organizations_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrganizationMembership(Base):
    """Administrative organization membership; it grants no workspace content access."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin')",
            name="ck_organization_memberships_role",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_organization_memberships_status",
        ),
        PrimaryKeyConstraint(
            "organization_id",
            "user_id",
            name="pk_organization_memberships",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    role: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Workspace(Base):
    """Primary Atlas data, policy, search, connection, and audit boundary."""

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'writes_frozen', 'closing', 'closed')",
            name="ck_workspaces_status",
        ),
        UniqueConstraint("organization_id", "slug", name="uq_workspaces_org_slug"),
        UniqueConstraint(
            "workspace_id",
            "organization_id",
            name="uq_workspaces_id_organization",
        ),
        Index("ix_workspaces_cell_id", "cell_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        "workspace_id", Uuid, primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    cell_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cells.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    time_zone: Mapped[str] = mapped_column(String(64), server_default="UTC")
    locale: Mapped[str] = mapped_column(String(32), server_default="en")
    settings: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default="{}", default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEvent(Base):
    """Immutable accountability record emitted by the H1-01 bootstrap."""

    __tablename__ = "audit_events"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_audit_events"),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_audit_events_workspace",
        ),
        Index("ix_audit_events_workspace_recorded", "workspace_id", "recorded_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default="{}", default=dict
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OutboxEvent(Base):
    """Transactional domain-event record for reliable downstream publication."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_outbox_events"),
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            ondelete="RESTRICT",
            name="fk_outbox_events_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_sequence",
            name="uq_outbox_aggregate_sequence",
        ),
        Index("ix_outbox_events_unpublished", "published_at", "recorded_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[int] = mapped_column(server_default="1")
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    aggregate_sequence: Mapped[int] = mapped_column(server_default="1")
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
