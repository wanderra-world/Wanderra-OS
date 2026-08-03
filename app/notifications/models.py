"""Workspace-owned H3-09 notification persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
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

TENANT = ("organization_id", "workspace_id", "cell_id")
WORKSPACE = ("workspace_id", "organization_id", "cell_id")
WORKSPACE_TARGET = ("workspaces.workspace_id", "workspaces.organization_id", "workspaces.cell_id")


class TenantMixin:
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cell_id: Mapped[uuid.UUID] = mapped_column(Uuid)


def workspace_args(name: str) -> tuple[ForeignKeyConstraint]:
    return (ForeignKeyConstraint(WORKSPACE, WORKSPACE_TARGET, ondelete="RESTRICT", name=name),)


class NotificationTemplateRecord(TenantMixin, Base):
    __tablename__ = "notification_templates"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_notification_templates"),
        UniqueConstraint(*TENANT, "template_key", name="uq_notification_template_key"),
        *workspace_args("fk_notification_templates_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    template_key: Mapped[str] = mapped_column(String(128))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationTemplateVersion(TenantMixin, Base):
    __tablename__ = "notification_template_versions"
    __table_args__ = (
        PrimaryKeyConstraint(
            *TENANT, "template_id", "version", name="pk_notification_template_versions"
        ),
        ForeignKeyConstraint(
            (*TENANT, "template_id"),
            (
                "notification_templates.organization_id",
                "notification_templates.workspace_id",
                "notification_templates.cell_id",
                "notification_templates.id",
            ),
            ondelete="RESTRICT",
            name="fk_notification_template_versions_template",
        ),
    )
    template_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    allowed_variables_json: Mapped[str] = mapped_column(Text)
    maximum_classification: Mapped[str] = mapped_column(String(16))
    template_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationPreferenceRecord(TenantMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "user_id", "channel", name="pk_notification_preferences"),
        *workspace_args("fk_notification_preferences_workspace"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean)
    maximum_classification: Mapped[str] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(String(64))
    quiet_start: Mapped[str | None] = mapped_column(String(8))
    quiet_end: Mapped[str | None] = mapped_column(String(8))
    digest_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    policy_version: Mapped[int] = mapped_column(Integer)


class NotificationIntentRecord(TenantMixin, Base):
    __tablename__ = "notification_intents"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_notification_intents"),
        UniqueConstraint(*TENANT, "intent_key", name="uq_notification_intent_key"),
        UniqueConstraint(*TENANT, "deduplication_key", name="uq_notification_deduplication"),
        *workspace_args("fk_notification_intents_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    intent_key: Mapped[str] = mapped_column(String(256))
    deduplication_key: Mapped[str] = mapped_column(String(256))
    intent_digest: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    destination_reference: Mapped[str] = mapped_column(String(256))
    template_key: Mapped[str] = mapped_column(String(128))
    template_version: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[int] = mapped_column(Integer)
    variables_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))
    deliver_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationDigest(TenantMixin, Base):
    __tablename__ = "notification_digests"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_notification_digests"),
        UniqueConstraint(*TENANT, "digest_key", name="uq_notification_digest_key"),
        *workspace_args("fk_notification_digests_workspace"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    digest_key: Mapped[str] = mapped_column(String(256))
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(128))
    window_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24))


class NotificationAttempt(TenantMixin, Base):
    __tablename__ = "notification_attempts"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_notification_attempts"),
        ForeignKeyConstraint(
            (*TENANT, "intent_id"),
            (
                "notification_intents.organization_id",
                "notification_intents.workspace_id",
                "notification_intents.cell_id",
                "notification_intents.id",
            ),
            ondelete="RESTRICT",
            name="fk_notification_attempts_intent",
        ),
        UniqueConstraint(
            *TENANT, "intent_id", "attempt_number", name="uq_notification_attempt_number"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_number: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(128))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24))
    retry_category: Mapped[str | None] = mapped_column(String(24))
    rendered_digest: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationReceipt(TenantMixin, Base):
    __tablename__ = "notification_receipts"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_notification_receipts"),
        ForeignKeyConstraint(
            (*TENANT, "attempt_id"),
            (
                "notification_attempts.organization_id",
                "notification_attempts.workspace_id",
                "notification_attempts.cell_id",
                "notification_attempts.id",
            ),
            ondelete="RESTRICT",
            name="fk_notification_receipts_attempt",
        ),
        UniqueConstraint(*TENANT, "attempt_id", name="uq_notification_receipt_attempt"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(String(24))
    receipt_reference_digest: Mapped[str | None] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NotificationInboxEntry(TenantMixin, Base):
    __tablename__ = "notification_inbox_entries"
    __table_args__ = (
        PrimaryKeyConstraint(*TENANT, "id", name="pk_notification_inbox_entries"),
        ForeignKeyConstraint(
            (*TENANT, "intent_id"),
            (
                "notification_intents.organization_id",
                "notification_intents.workspace_id",
                "notification_intents.cell_id",
                "notification_intents.id",
            ),
            ondelete="RESTRICT",
            name="fk_notification_inbox_intent",
        ),
        UniqueConstraint(*TENANT, "intent_id", name="uq_notification_inbox_intent"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    subject: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(16))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
