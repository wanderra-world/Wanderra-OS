"""Workspace-owned persistence for the constrained H3-01 Resource Graph."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

TENANT_RESOURCE_FK = ("organization_id", "workspace_id", "cell_id", "resource_id")
RESOURCE_TARGET = (
    "resources.organization_id",
    "resources.workspace_id",
    "resources.cell_id",
    "resources.id",
)


class ResourceProjection(Base):
    """One typed operational owner bound one-to-one to a resource identity."""

    __tablename__ = "resource_projections"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "id",
            name="pk_resource_projections",
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "resource_id",
            name="uq_resource_projections_resource",
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "id",
            "resource_type",
            name="uq_resource_projections_identity_type",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "organization_id", "cell_id"],
            ["workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id"],
            ondelete="RESTRICT",
            name="fk_resource_projections_workspace",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "resource_id", "resource_type"],
            [
                "resources.organization_id",
                "resources.workspace_id",
                "resources.cell_id",
                "resources.id",
                "resources.resource_type",
            ],
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
            name="fk_resource_projections_resource",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resource(Base):
    """Canonical connectable identity with exactly one typed projection owner."""

    __tablename__ = "resources"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resources"
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "id",
            "resource_type",
            name="uq_resources_identity_type",
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "projection_id",
            name="uq_resources_projection",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "organization_id", "cell_id"],
            ["workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id"],
            ondelete="RESTRICT",
            name="fk_resources_workspace",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "projection_id", "resource_type"],
            [
                "resource_projections.organization_id",
                "resource_projections.workspace_id",
                "resource_projections.cell_id",
                "resource_projections.id",
                "resource_projections.resource_type",
            ],
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
            name="fk_resources_projection",
        ),
        CheckConstraint(
            "resource_type IN "
            "('contact','company','project','task','communication','meeting','document')",
            name="ck_resources_type",
        ),
        CheckConstraint("status IN ('active','deleted')", name="ck_resources_status"),
        CheckConstraint("version > 0", name="ck_resources_version"),
        Index("ix_resources_workspace_type", "workspace_id", "resource_type", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_type: Mapped[str] = mapped_column(String(32))
    projection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResourceRelationship(Base):
    __tablename__ = "resource_relationships"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_relationships"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "organization_id", "cell_id"],
            ["workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id"],
            ondelete="RESTRICT",
            name="fk_resource_relationships_workspace",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "source_resource_id"],
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_relationships_source",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "target_resource_id"],
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_relationships_target",
        ),
        UniqueConstraint(
            "workspace_id",
            "relationship_type",
            "source_resource_id",
            "target_resource_id",
            name="uq_resource_relationships_edge",
        ),
        CheckConstraint(
            "source_resource_id <> target_resource_id", name="ck_resource_relationships_distinct"
        ),
        CheckConstraint("status IN ('active','deleted')", name="ck_resource_relationships_status"),
        CheckConstraint("version > 0", name="ck_resource_relationships_version"),
        Index("ix_resource_relationships_source", "workspace_id", "source_resource_id", "status"),
        Index("ix_resource_relationships_target", "workspace_id", "target_resource_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    relationship_type: Mapped[str] = mapped_column(String(64))
    source_resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    target_resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceTag(Base):
    __tablename__ = "resource_tags"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "resource_id",
            "tag",
            name="pk_resource_tags",
        ),
        ForeignKeyConstraint(
            TENANT_RESOURCE_FK,
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_tags_resource",
        ),
        CheckConstraint(
            "tag = lower(tag) AND length(tag) BETWEEN 1 AND 64", name="ck_resource_tags_value"
        ),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tag: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceAttachment(Base):
    __tablename__ = "resource_attachments"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_attachments"
        ),
        ForeignKeyConstraint(
            TENANT_RESOURCE_FK,
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_attachments_resource",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "cell_id", "attachment_resource_id"],
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_attachments_attachment",
        ),
        UniqueConstraint(
            "workspace_id",
            "resource_id",
            "attachment_resource_id",
            name="uq_resource_attachments_pair",
        ),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attachment_resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceNote(Base):
    __tablename__ = "resource_notes"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_notes"
        ),
        ForeignKeyConstraint(
            TENANT_RESOURCE_FK,
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_notes_resource",
        ),
        CheckConstraint("note_kind IN ('human','ai')", name="ck_resource_notes_kind"),
        CheckConstraint("length(content) BETWEEN 1 AND 10000", name="ck_resource_notes_content"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    note_kind: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model_reference: Mapped[str | None] = mapped_column(String(128))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceOwnership(Base):
    __tablename__ = "resource_ownerships"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id",
            "workspace_id",
            "cell_id",
            "resource_id",
            name="pk_resource_ownerships",
        ),
        ForeignKeyConstraint(
            TENANT_RESOURCE_FK,
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_ownerships_resource",
        ),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    assigned_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ResourceGrant(Base):
    __tablename__ = "resource_grants"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_grants"
        ),
        ForeignKeyConstraint(
            TENANT_RESOURCE_FK,
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_grants_resource",
        ),
        CheckConstraint(
            "permission_key IN ('read_content','update_content','delete_content')",
            name="ck_resource_grants_permission",
        ),
        CheckConstraint("status IN ('active','revoked')", name="ck_resource_grants_status"),
        UniqueConstraint(
            "workspace_id",
            "resource_id",
            "grantee_user_id",
            "permission_key",
            name="uq_resource_grants_subject_permission",
        ),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    grantee_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    permission_key: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceExternalLink(Base):
    __tablename__ = "resource_external_links"
    __table_args__ = (
        PrimaryKeyConstraint(
            "organization_id", "workspace_id", "cell_id", "id", name="pk_resource_external_links"
        ),
        ForeignKeyConstraint(
            TENANT_RESOURCE_FK,
            RESOURCE_TARGET,
            ondelete="RESTRICT",
            name="fk_resource_external_links_resource",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "external_reference_id"],
            ["provider_external_references.workspace_id", "provider_external_references.id"],
            ondelete="RESTRICT",
            name="fk_resource_external_links_external_reference",
        ),
        UniqueConstraint(
            "workspace_id",
            "external_reference_id",
            name="uq_resource_external_links_external_reference",
        ),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    external_reference_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    linked_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
