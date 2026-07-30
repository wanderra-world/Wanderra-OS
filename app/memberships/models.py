"""Persistence models for H1-04 workspace memberships."""

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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class FixedMembershipRole(Base):
    """Versioned fixed role name without permissions or policy behavior."""

    __tablename__ = "fixed_membership_roles"
    __table_args__ = (
        PrimaryKeyConstraint("role_key", "version", name="pk_fixed_membership_roles"),
        CheckConstraint(
            "scope IN ('organization', 'workspace')",
            name="ck_fixed_membership_roles_scope",
        ),
        CheckConstraint("version > 0", name="ck_fixed_membership_roles_version"),
    )

    role_key: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkspaceMembership(Base):
    """Canonical user-to-organization-to-workspace membership."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "id", name="pk_workspace_memberships"),
        ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["workspaces.workspace_id", "workspaces.organization_id"],
            ondelete="RESTRICT",
            name="fk_workspace_memberships_workspace_organization",
        ),
        ForeignKeyConstraint(
            ["role_key", "role_version"],
            ["fixed_membership_roles.role_key", "fixed_membership_roles.version"],
            ondelete="RESTRICT",
            name="fk_workspace_memberships_fixed_role",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "invitation_token_id"],
            [
                "identity_lifecycle_tokens.workspace_id",
                "identity_lifecycle_tokens.id",
            ],
            ondelete="RESTRICT",
            name="fk_workspace_memberships_invitation",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "accepted_invitation_token_id"],
            [
                "identity_lifecycle_tokens.workspace_id",
                "identity_lifecycle_tokens.id",
            ],
            ondelete="RESTRICT",
            name="fk_workspace_memberships_accepted_invitation",
        ),
        CheckConstraint(
            """
            role_key IN ('workspace_owner', 'workspace_admin', 'member', 'viewer')
            """,
            name="ck_workspace_memberships_workspace_role",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_workspace_memberships_status",
        ),
        CheckConstraint("version > 0", name="ck_workspace_memberships_version"),
        CheckConstraint(
            "origin IN ('direct', 'invitation', 'migration')",
            name="ck_workspace_memberships_origin",
        ),
        CheckConstraint(
            """
            (
                status = 'invited'
                AND activated_at IS NULL
                AND revoked_at IS NULL
            )
            OR
            (
                status IN ('active', 'suspended')
                AND activated_at IS NOT NULL
                AND revoked_at IS NULL
            )
            OR
            (
                status = 'revoked'
                AND revoked_at IS NOT NULL
            )
            """,
            name="ck_workspace_memberships_lifecycle",
        ),
        UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_memberships_workspace_user",
        ),
        UniqueConstraint(
            "workspace_id",
            "invitation_token_id",
            name="uq_workspace_memberships_invitation",
        ),
        UniqueConstraint(
            "workspace_id",
            "accepted_invitation_token_id",
            name="uq_workspace_memberships_accepted_invitation",
        ),
        Index(
            "ix_workspace_memberships_user_status",
            "user_id",
            "status",
        ),
        Index(
            "ix_workspace_memberships_workspace_role_status",
            "workspace_id",
            "role_key",
            "status",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    role_key: Mapped[str] = mapped_column(String(64))
    role_version: Mapped[int] = mapped_column(Integer, server_default="1")
    status: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    invitation_token_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    accepted_invitation_token_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(128))
    origin: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
