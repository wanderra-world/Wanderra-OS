"""Canonical permission and fixed-role mapping models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Permission(Base):
    """Versioned stable operation understood by Atlas Core."""

    __tablename__ = "permissions"
    __table_args__ = (
        PrimaryKeyConstraint("permission_key", "version", name="pk_permissions"),
        CheckConstraint("version > 0", name="ck_permissions_version"),
    )

    permission_key: Mapped[str] = mapped_column(String(96))
    version: Mapped[int]
    description: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RolePermission(Base):
    """Explicit allow or deny rule for one fixed role and permission version."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "role_key",
            "role_version",
            "permission_key",
            "permission_version",
            "effect",
            name="pk_role_permissions",
        ),
        ForeignKeyConstraint(
            ["role_key", "role_version"],
            ["fixed_membership_roles.role_key", "fixed_membership_roles.version"],
            ondelete="RESTRICT",
            name="fk_role_permissions_role",
        ),
        ForeignKeyConstraint(
            ["permission_key", "permission_version"],
            ["permissions.permission_key", "permissions.version"],
            ondelete="RESTRICT",
            name="fk_role_permissions_permission",
        ),
        CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="ck_role_permissions_effect",
        ),
    )

    role_key: Mapped[str] = mapped_column(String(64))
    role_version: Mapped[int]
    permission_key: Mapped[str] = mapped_column(String(96))
    permission_version: Mapped[int]
    effect: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
