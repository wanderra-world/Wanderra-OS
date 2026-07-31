"""Contract tests for the provider-neutral H2-05 capability boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from app.provider_capabilities.calendar import CalendarEvent, CalendarMoment
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    ExtensionEnvelope,
    OpaqueCursor,
    ProviderCapabilityError,
    RetryClassification,
    VersionPrecondition,
    from_wire,
    to_wire,
)
from app.provider_capabilities.email import EmailAddress, EmailMessage
from app.provider_capabilities.storage import StorageObject


def test_contract_dtos_are_immutable_and_serialize_without_provider_types() -> None:
    message = EmailMessage(
        external_id="message-1",
        thread_external_id="thread-1",
        sender=EmailAddress(address="sender@example.test", display_name="Sender"),
        recipients=(EmailAddress(address="recipient@example.test"),),
        subject="Canonical message",
        body_text="Provider-neutral content",
        labels=("unread",),
        received_at=datetime(2026, 7, 31, 10, 30, tzinfo=UTC),
        version="v1",
        extensions=ExtensionEnvelope({"mock.example/label_color": "blue"}),
    )

    with pytest.raises(FrozenInstanceError):
        message.subject = "changed"  # type: ignore[misc]

    wire = to_wire(message)
    assert wire["received_at"] == "2026-07-31T10:30:00+00:00"
    assert wire["sender"]["address"] == "sender@example.test"
    assert wire["extensions"] == {"mock.example/label_color": "blue"}
    assert from_wire(EmailMessage, wire) == message
    assert "google" not in repr(wire).lower()


def test_canonical_time_preserves_offsets_and_all_day_dates() -> None:
    offset_time = datetime.fromisoformat("2026-08-01T15:00:00+02:00")
    timed = CalendarMoment(date_time=offset_time, time_zone="Europe/Stockholm")
    all_day = CalendarMoment(date=date(2026, 8, 2))

    assert to_wire(timed)["date_time"] == "2026-08-01T15:00:00+02:00"
    assert from_wire(CalendarMoment, to_wire(timed)) == timed
    assert from_wire(CalendarMoment, to_wire(all_day)) == all_day

    with pytest.raises(ValueError, match="exactly one"):
        CalendarMoment()
    with pytest.raises(ValueError, match="timezone-aware"):
        CalendarMoment(date_time=datetime(2026, 8, 1, 15, 0))


def test_opaque_cursor_and_extension_envelope_validate_the_boundary() -> None:
    assert OpaqueCursor("opaque-value").value == "opaque-value"
    with pytest.raises(ValueError, match="non-empty"):
        OpaqueCursor("")
    with pytest.raises(ValueError, match="namespaced"):
        ExtensionEnvelope({"not_namespaced": True})
    with pytest.raises(TypeError, match="JSON-compatible"):
        ExtensionEnvelope({"mock.example/value": object()})


def test_version_precondition_requires_exactly_one_provider_token() -> None:
    assert VersionPrecondition(etag='"etag-1"').etag == '"etag-1"'
    assert VersionPrecondition(version="42").version == "42"
    with pytest.raises(ValueError, match="exactly one"):
        VersionPrecondition()
    with pytest.raises(ValueError, match="exactly one"):
        VersionPrecondition(etag="etag", version="42")


def test_capability_registry_discovers_and_negotiates_versions() -> None:
    registry = CapabilityRegistry()
    registry.register(
        "mock.example",
        (
            CapabilityDescriptor("email", 1, ("profile", "list", "send")),
            CapabilityDescriptor("storage", 1, ("list", "download")),
        ),
    )

    assert registry.discover("mock.example", "email").operations == (
        "profile",
        "list",
        "send",
    )
    assert registry.negotiate("mock.example", {"email": (1,), "storage": (1,)}).versions == {
        "email": 1,
        "storage": 1,
    }
    with pytest.raises(ProviderCapabilityError) as unsupported:
        registry.negotiate("mock.example", {"calendar": (1,)})
    assert unsupported.value.category is CanonicalErrorCategory.UNSUPPORTED_CAPABILITY
    assert unsupported.value.retry is RetryClassification.NEVER


@pytest.mark.parametrize(
    ("category", "retry"),
    (
        (CanonicalErrorCategory.AUTHENTICATION, RetryClassification.REFRESH_AUTH),
        (CanonicalErrorCategory.AUTHORIZATION, RetryClassification.NEVER),
        (CanonicalErrorCategory.SCOPE, RetryClassification.NEVER),
        (CanonicalErrorCategory.RATE_LIMIT, RetryClassification.BACKOFF),
        (CanonicalErrorCategory.TRANSIENT, RetryClassification.BACKOFF),
        (CanonicalErrorCategory.CONFLICT, RetryClassification.REFRESH_RESOURCE),
        (CanonicalErrorCategory.NOT_FOUND, RetryClassification.NEVER),
        (CanonicalErrorCategory.INVALID_INPUT, RetryClassification.NEVER),
        (CanonicalErrorCategory.QUOTA, RetryClassification.BACKOFF),
        (CanonicalErrorCategory.UNSUPPORTED_CAPABILITY, RetryClassification.NEVER),
    ),
)
def test_error_taxonomy_has_deterministic_retry_classification(
    category: CanonicalErrorCategory,
    retry: RetryClassification,
) -> None:
    error = ProviderCapabilityError(category, "Safe canonical message")
    assert error.retry is retry
    assert str(error) == "Safe canonical message"
    assert to_wire(error)["category"] == category.value


def test_phase_one_resource_shapes_remain_provider_neutral() -> None:
    event = CalendarEvent(
        external_id="event-1",
        calendar_external_id="primary",
        status="confirmed",
        summary="Atlas",
        start=CalendarMoment(date_time=datetime(2026, 8, 1, 15, tzinfo=UTC)),
        end=CalendarMoment(date_time=datetime(2026, 8, 1, 15, 30, tzinfo=UTC)),
        version="7",
    )
    storage = StorageObject(
        external_id="file-1",
        name="atlas.txt",
        media_type="text/plain",
        size=5,
        version="9",
        modified_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert to_wire(event)["start"]["date_time"].endswith("+00:00")
    assert to_wire(storage)["media_type"] == "text/plain"

