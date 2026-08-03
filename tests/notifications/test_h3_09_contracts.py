from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest

from app.notifications.contracts import (
    ChannelCapability,
    ChannelResult,
    DeliveryOutcome,
    DeliveryPolicy,
    NotificationError,
    NotificationIntent,
    NotificationPreference,
    NotificationTemplate,
    QuietPeriod,
    RetryCategory,
    decide_retry,
    intent_digest,
    render_template,
    resolve_delivery,
    validate_channel_result,
)


def intent(**overrides: object) -> NotificationIntent:
    values: dict[str, object] = {
        "intent_id": uuid4(),
        "intent_key": "task:42:completed",
        "deduplication_key": "task:42:completed:user:7",
        "source_type": "task",
        "source_id": uuid4(),
        "recipient_user_id": uuid4(),
        "destination_reference": "user:7",
        "template_key": "task.completed",
        "template_version": 1,
        "classification": "internal",
        "purpose": "transactional",
        "policy_version": 2,
        "variables": {"title": "Review"},
    }
    values.update(overrides)
    return NotificationIntent(**values)


def test_intent_digest_is_canonical_and_key_reuse_fails_closed() -> None:
    value = intent(variables={"b": 2, "a": 1})
    same = value.model_copy(update={"variables": {"a": 1, "b": 2}})
    assert intent_digest(value) == intent_digest(same)
    changed = value.model_copy(update={"purpose": "security"})
    assert intent_digest(value) != intent_digest(changed)


def test_template_is_inert_versioned_and_minimized() -> None:
    template = NotificationTemplate(
        key="task.completed",
        version=1,
        subject="Task: {title}",
        body="{title} is complete",
        allowed_variables=("title",),
        maximum_classification="confidential",
    )
    assert render_template(template, {"title": "Review", "secret": "never"}) == (
        "Task: Review",
        "Review is complete",
    )
    with pytest.raises(ValueError, match="executable"):
        NotificationTemplate(
            key="bad", version=1, subject="x", body="{{ python:call }}", allowed_variables=()
        )


def test_preferences_authorization_classification_and_quiet_period_are_enforced() -> None:
    now = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    preference = NotificationPreference(
        channel="in_app",
        enabled=True,
        maximum_classification="internal",
        timezone="Europe/Stockholm",
        quiet_period=QuietPeriod(start=time(2, 0), end=time(7, 0)),
    )
    capability = ChannelCapability(
        channel="in_app", maximum_classification="restricted", supports_receipts=True
    )
    decision = resolve_delivery(
        intent(), preference, capability, now=now, authorized=True, destination_eligible=True
    )
    assert decision.outcome is DeliveryOutcome.DEFERRED
    assert decision.deliver_after > now

    with pytest.raises(NotificationError, match="authorization"):
        resolve_delivery(intent(), preference, capability, now=now, authorized=False)
    with pytest.raises(NotificationError, match="classification"):
        resolve_delivery(
            intent(classification="confidential"),
            preference,
            capability,
            now=now + timedelta(hours=8),
            authorized=True,
        )
    with pytest.raises(NotificationError, match="opted out"):
        resolve_delivery(
            intent(),
            preference.model_copy(update={"enabled": False}),
            capability,
            now=now,
            authorized=True,
        )


def test_delivery_outcomes_and_retry_categories_are_explicit() -> None:
    assert RetryCategory.TRANSIENT.value == "transient"
    assert DeliveryOutcome.UNCERTAIN.value == "uncertain"
    assert DeliveryOutcome.BOUNCED.value == "bounced"


def test_secrets_are_rejected_and_verified_receipts_are_required() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        intent(variables={"access_token": "never"})
    with pytest.raises(NotificationError, match="verified receipt"):
        validate_channel_result(
            DeliveryOutcome.DELIVERED,
            supports_receipts=True,
            receipt_reference=None,
        )
    validate_channel_result(
        DeliveryOutcome.UNCERTAIN,
        supports_receipts=True,
        receipt_reference=None,
    )


def test_retry_rate_limit_and_escalation_are_deterministic() -> None:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    decision = decide_retry(
        result=ChannelResult(
            outcome=DeliveryOutcome.FAILED,
            retry_category=RetryCategory.TRANSIENT,
        ),
        attempt_number=2,
        attempts_in_rate_window=10,
        policy=DeliveryPolicy(
            maximum_attempts=3,
            retry_delay_seconds=30,
            escalation_attempt=2,
            rate_limit_per_window=10,
        ),
        now=now,
    )
    assert decision.outcome is DeliveryOutcome.DEFERRED
    assert decision.next_attempt_at == now + timedelta(seconds=60)
    assert decision.escalated
