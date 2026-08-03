"""Typed, deterministic contracts for the provider-neutral Notification Center."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from string import Formatter
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, model_validator


class NotificationError(ValueError):
    pass


class DeliveryOutcome(StrEnum):
    SCHEDULED = "scheduled"
    DEFERRED = "deferred"
    DELIVERED = "delivered"
    SUPPRESSED = "suppressed"
    FAILED = "failed"
    BOUNCED = "bounced"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"


class RetryCategory(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    BOUNCE = "bounce"
    UNCERTAIN = "uncertain"


CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
CLASSIFICATION_RANK = {value: index for index, value in enumerate(CLASSIFICATIONS)}
SAFE_KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


class QuietPeriod(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: time
    end: time

    @model_validator(mode="after")
    def validate_period(self) -> QuietPeriod:
        if self.start == self.end:
            raise NotificationError("quiet period cannot span the entire day")
        return self


class NotificationTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str
    version: int
    subject: str
    body: str
    allowed_variables: tuple[str, ...]
    maximum_classification: str = "internal"

    @model_validator(mode="after")
    def validate_template(self) -> NotificationTemplate:
        if not SAFE_KEY.fullmatch(self.key) or self.version < 1:
            raise NotificationError("template identity is invalid")
        if self.maximum_classification not in CLASSIFICATION_RANK:
            raise NotificationError("template classification is invalid")
        inert_markers = ("{{", "}}", "{%", "%}", "python:", "sql:", "prompt:")
        combined = (self.subject + self.body).casefold()
        if any(marker in combined for marker in inert_markers):
            raise NotificationError("template contains executable syntax")
        fields = {name for _, name, _, _ in Formatter().parse(self.subject + self.body) if name}
        if fields - set(self.allowed_variables):
            raise NotificationError("template references an unapproved variable")
        return self


class NotificationIntent(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent_id: uuid.UUID
    intent_key: str
    deduplication_key: str
    source_type: str
    source_id: uuid.UUID
    recipient_user_id: uuid.UUID
    destination_reference: str
    template_key: str
    template_version: int
    classification: str
    purpose: str
    policy_version: int
    variables: dict[str, object]

    @model_validator(mode="after")
    def validate_intent(self) -> NotificationIntent:
        for value in (self.intent_key, self.deduplication_key, self.source_type, self.purpose):
            if not value.strip() or len(value) > 256:
                raise NotificationError("notification intent identity is invalid")
        if not SAFE_KEY.fullmatch(self.template_key):
            raise NotificationError("notification template key is invalid")
        if self.classification not in CLASSIFICATION_RANK:
            raise NotificationError("notification classification is invalid")
        if self.template_version < 1 or self.policy_version < 1:
            raise NotificationError("notification version is invalid")
        serialized = json.dumps(self.variables, sort_keys=True, separators=(",", ":"))
        sensitive = ("password", "secret", "token", "credential", "raw_payload")
        if any(marker in key.casefold() for key in self.variables for marker in sensitive):
            raise NotificationError("sensitive notification variables are prohibited")
        if len(serialized.encode()) > 32_768:
            raise NotificationError("notification variables exceed the size limit")
        return self


class NotificationPreference(BaseModel):
    model_config = ConfigDict(frozen=True)
    channel: str
    enabled: bool
    maximum_classification: str
    timezone: str
    quiet_period: QuietPeriod | None = None
    digest: bool = False

    @model_validator(mode="after")
    def validate_preference(self) -> NotificationPreference:
        if not SAFE_KEY.fullmatch(self.channel):
            raise NotificationError("notification channel is invalid")
        if self.maximum_classification not in CLASSIFICATION_RANK:
            raise NotificationError("preference classification is invalid")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise NotificationError("preference timezone is invalid") from error
        return self


class ChannelCapability(BaseModel):
    model_config = ConfigDict(frozen=True)
    channel: str
    maximum_classification: str
    supports_receipts: bool
    supports_redaction: bool = True

    @model_validator(mode="after")
    def validate_capability(self) -> ChannelCapability:
        if not SAFE_KEY.fullmatch(self.channel):
            raise NotificationError("channel capability identity is invalid")
        if self.maximum_classification not in CLASSIFICATION_RANK:
            raise NotificationError("channel classification is invalid")
        return self


class DeliveryDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: DeliveryOutcome
    deliver_after: datetime
    reason: str


class DeliveryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    maximum_attempts: int = 3
    retry_delay_seconds: int = 60
    escalation_attempt: int | None = None
    rate_limit_per_window: int = 100

    @model_validator(mode="after")
    def validate_policy(self) -> DeliveryPolicy:
        if self.maximum_attempts < 1 or self.retry_delay_seconds < 1:
            raise NotificationError("delivery retry policy is invalid")
        if self.rate_limit_per_window < 1:
            raise NotificationError("delivery rate limit is invalid")
        if self.escalation_attempt is not None and not (
            1 <= self.escalation_attempt <= self.maximum_attempts
        ):
            raise NotificationError("delivery escalation policy is invalid")
        return self


class RetryDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: DeliveryOutcome
    next_attempt_at: datetime | None
    escalated: bool


class ChannelRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    attempt_id: uuid.UUID
    destination_reference: str
    subject: str
    body: str
    classification: str
    idempotency_key: str


class ChannelResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: DeliveryOutcome
    receipt_reference: str | None = None
    retry_category: RetryCategory | None = None


class NotificationChannel(Protocol):
    capability: ChannelCapability

    async def deliver(self, request: ChannelRequest) -> ChannelResult: ...


def intent_digest(intent: NotificationIntent) -> str:
    payload = intent.model_dump(mode="json", exclude={"intent_id"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def render_template(
    template: NotificationTemplate, variables: dict[str, object]
) -> tuple[str, str]:
    minimized = {key: variables[key] for key in template.allowed_variables if key in variables}
    try:
        return template.subject.format_map(minimized), template.body.format_map(minimized)
    except KeyError as error:
        raise NotificationError("required template variable is missing") from error


def _quiet_end(now: datetime, timezone: str, period: QuietPeriod) -> datetime | None:
    local = now.astimezone(ZoneInfo(timezone))
    current = local.timetz().replace(tzinfo=None)
    crosses_midnight = period.start > period.end
    quiet = (
        current >= period.start or current < period.end
        if crosses_midnight
        else period.start <= current < period.end
    )
    if not quiet:
        return None
    end_date = local.date()
    if crosses_midnight and current >= period.start:
        end_date += timedelta(days=1)
    candidate = datetime.combine(end_date, period.end, tzinfo=ZoneInfo(timezone))
    return candidate.astimezone(UTC)


def resolve_delivery(
    intent: NotificationIntent,
    preference: NotificationPreference,
    capability: ChannelCapability,
    *,
    now: datetime,
    authorized: bool,
    destination_eligible: bool = True,
) -> DeliveryDecision:
    if now.tzinfo is None:
        raise NotificationError("delivery clock must be timezone-aware")
    if not authorized or not destination_eligible:
        raise NotificationError("notification authorization denied")
    if not preference.enabled:
        raise NotificationError("recipient opted out")
    if preference.channel != capability.channel:
        raise NotificationError("channel capability mismatch")
    effective = CLASSIFICATION_RANK[intent.classification]
    if (
        effective > CLASSIFICATION_RANK[preference.maximum_classification]
        or effective > CLASSIFICATION_RANK[capability.maximum_classification]
    ):
        raise NotificationError("channel classification is insufficient")
    quiet_end = (
        _quiet_end(now, preference.timezone, preference.quiet_period)
        if preference.quiet_period
        else None
    )
    if quiet_end is not None:
        return DeliveryDecision(
            outcome=DeliveryOutcome.DEFERRED,
            deliver_after=quiet_end,
            reason="quiet_period",
        )
    return DeliveryDecision(outcome=DeliveryOutcome.SCHEDULED, deliver_after=now, reason="eligible")


def validate_channel_result(
    outcome: DeliveryOutcome,
    *,
    supports_receipts: bool,
    receipt_reference: str | None,
) -> None:
    if outcome is DeliveryOutcome.DELIVERED and supports_receipts and not receipt_reference:
        raise NotificationError("delivered outcome requires a verified receipt")
    if outcome in {DeliveryOutcome.SCHEDULED, DeliveryOutcome.DEFERRED}:
        raise NotificationError("channel returned a non-terminal delivery outcome")


def decide_retry(
    *,
    result: ChannelResult,
    attempt_number: int,
    attempts_in_rate_window: int,
    policy: DeliveryPolicy,
    now: datetime,
) -> RetryDecision:
    if now.tzinfo is None or attempt_number < 1 or attempts_in_rate_window < 0:
        raise NotificationError("delivery attempt context is invalid")
    validate_channel_result(
        result.outcome,
        supports_receipts=False,
        receipt_reference=result.receipt_reference,
    )
    escalated = (
        policy.escalation_attempt is not None and attempt_number >= policy.escalation_attempt
    )
    retryable = result.retry_category is RetryCategory.TRANSIENT
    exhausted = attempt_number >= policy.maximum_attempts
    rate_limited = attempts_in_rate_window >= policy.rate_limit_per_window
    if retryable and not exhausted:
        multiplier = 2 ** (attempt_number - 1)
        if rate_limited:
            multiplier = max(multiplier, 2)
        return RetryDecision(
            outcome=DeliveryOutcome.DEFERRED,
            next_attempt_at=now + timedelta(seconds=policy.retry_delay_seconds * multiplier),
            escalated=escalated,
        )
    return RetryDecision(
        outcome=result.outcome,
        next_attempt_at=None,
        escalated=escalated,
    )
