"""Authorized transactional H3-09 Notification Center service."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.notifications.contracts import (
    ChannelCapability,
    NotificationError,
    NotificationIntent,
    NotificationPreference,
    NotificationTemplate,
    intent_digest,
    render_template,
    resolve_delivery,
)
from app.notifications.models import NotificationInboxEntry, NotificationIntentRecord
from app.notifications.repository import NotificationRepository
from app.tenancy.models import OutboxEvent


class NotificationAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class NotificationService:
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: NotificationAuthorizer,
    ) -> None:
        self.session, self.context, self.authorizer = session, context, authorizer
        self.repository = NotificationRepository(session, context)
        self.audit = AuditWriterService(session, context)

    def _tenant(self) -> dict[str, uuid.UUID]:
        tenant = self.context.tenant
        return {
            "organization_id": tenant.organization_id,
            "workspace_id": tenant.workspace_id,
            "cell_id": tenant.cell_id,
        }

    async def create_intent(
        self,
        intent: NotificationIntent,
        template: NotificationTemplate,
        preference: NotificationPreference,
        capability: ChannelCapability,
        *,
        now: datetime,
        destination_eligible: bool = True,
    ) -> NotificationIntentRecord:
        authorized = await self.authorizer.authorize(self.context, "notification.intent.create")
        if (template.key, template.version) != (
            intent.template_key,
            intent.template_version,
        ):
            raise NotificationError("notification template binding mismatch")
        subject, body = render_template(template, intent.variables)
        decision = resolve_delivery(
            intent,
            preference,
            capability,
            now=now,
            authorized=authorized,
            destination_eligible=destination_eligible,
        )
        digest = intent_digest(intent)
        existing = await self.repository.intent_by_deduplication_key(intent.deduplication_key)
        if existing is not None:
            if existing.intent_digest != digest:
                raise NotificationError("notification deduplication key reuse changed input")
            return existing
        value = NotificationIntentRecord(
            **self._tenant(),
            id=intent.intent_id,
            intent_key=intent.intent_key,
            deduplication_key=intent.deduplication_key,
            intent_digest=digest,
            source_type=intent.source_type,
            source_id=intent.source_id,
            recipient_user_id=intent.recipient_user_id,
            destination_reference=intent.destination_reference,
            template_key=intent.template_key,
            template_version=intent.template_version,
            classification=intent.classification,
            purpose=intent.purpose,
            policy_version=intent.policy_version,
            variables_json=json.dumps(intent.variables, sort_keys=True, separators=(",", ":")),
            status=decision.outcome.value,
            deliver_after=decision.deliver_after,
            cancelled_at=None,
            created_at=now,
        )
        await self.repository.add(value)
        await self.repository.add(
            NotificationInboxEntry(
                **self._tenant(),
                id=uuid.uuid4(),
                intent_id=value.id,
                recipient_user_id=value.recipient_user_id,
                subject=subject,
                body=body,
                classification=value.classification,
                read_at=None,
                created_at=now,
            )
        )
        await self.audit.write(
            AuditInput(
                action="notification.intent.created",
                target_type="notification_intent",
                target_id=value.id,
                outcome="success",
                classification=value.classification,
                details={"status": value.status},
            )
        )
        self.session.add(
            OutboxEvent(
                workspace_id=self.context.tenant.workspace_id,
                id=uuid.uuid4(),
                event_type="notification.intent.created",
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="notification_intent",
                aggregate_id=value.id,
                aggregate_sequence=1,
                actor_id=self.context.actor.actor_id,
                correlation_id=self.context.request.correlation_id,
                classification=value.classification,
                idempotency_key=value.deduplication_key,
                payload_digest=hashlib.sha256(digest.encode()).hexdigest(),
                payload={"intent_id": str(value.id), "status": value.status},
                recorded_at=now,
                partition_key=now.strftime("%Y-%m"),
            )
        )
        await self.session.flush()
        return value
