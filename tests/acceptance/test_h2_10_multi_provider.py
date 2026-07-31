"""Integrated H2-10 provider-neutral conformance acceptance tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.integrations.calendar.adapter import GoogleCalendarAdapter
from app.integrations.drive.adapter import GoogleDriveAdapter
from app.integrations.gmail.adapter import GmailEmailAdapter
from app.provider_capabilities.calendar import CalendarEventCreate
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    MutationContext,
    ProviderCapabilityError,
    VersionPrecondition,
)
from app.provider_capabilities.email import EmailListRequest, EmailMessageCreate
from app.provider_capabilities.storage import StorageObjectCreate
from app.provider_capabilities.testing import DeterministicMockProvider
from tests.calendar_capability.test_h2_07_google_adapter import FakeCalendarApi
from tests.email_capability.test_h2_06_gmail_adapter import FakeGmailApi
from tests.storage_capability.test_h2_08_google_adapter import FakeDriveApi


@pytest.mark.asyncio
async def test_google_adapters_expose_only_canonical_capability_results() -> None:
    email = GmailEmailAdapter(FakeGmailApi())
    calendar = GoogleCalendarAdapter(FakeCalendarApi())
    storage = GoogleDriveAdapter(FakeDriveApi())

    messages = await email.list_messages(EmailListRequest())
    event = await calendar.create_event(
        CalendarEventCreate(
            calendar_external_id="primary",
            summary="Atlas",
            start=datetime(2026, 8, 1, 15, tzinfo=UTC),
            end=datetime(2026, 8, 1, 15, 30, tzinfo=UTC),
        ),
        MutationContext("google-event-create"),
    )
    stored = await storage.upload(
        StorageObjectCreate("atlas.txt", b"Atlas", "text/plain"),
        MutationContext("google-file-upload"),
    )

    assert messages.items[0].subject == "Canonical"
    assert event.external_id == "created"
    assert stored.external_id == "created"
    assert not hasattr(messages.items[0], "provider_payload")
    assert not hasattr(event, "provider_payload")
    assert not hasattr(stored, "provider_payload")


@pytest.mark.asyncio
async def test_two_synthetic_connections_are_isolated_and_provider_neutral() -> None:
    first = DeterministicMockProvider()
    second = DeterministicMockProvider()
    message = EmailMessageCreate(
        to=("recipient@example.test",), subject="Independent", body_text="Atlas"
    )

    first_result = await first.email.send_message(
        message, MutationContext("workspace-a-send")
    )
    assert first_result.external_id == "mail-2"
    assert len((await first.email.list_messages(EmailListRequest())).items) == 2
    assert len((await second.email.list_messages(EmailListRequest())).items) == 1

    second_result = await second.email.send_message(
        message, MutationContext("workspace-a-send")
    )
    assert second_result.external_id == "mail-2"


@pytest.mark.asyncio
async def test_mock_provider_replay_and_stale_version_fail_closed() -> None:
    provider = DeterministicMockProvider()
    first = EmailMessageCreate(
        to=("one@example.test",), subject="One", body_text="One"
    )
    await provider.email.send_message(first, MutationContext("replay-key"))
    with pytest.raises(ProviderCapabilityError) as replay:
        await provider.email.send_message(
            EmailMessageCreate(
                to=("two@example.test",), subject="Two", body_text="Two"
            ),
            MutationContext("replay-key"),
        )
    assert replay.value.category is CanonicalErrorCategory.CONFLICT

    created = await provider.storage.upload(
        StorageObjectCreate("atlas.txt", b"Atlas", "text/plain"),
        MutationContext("upload-key"),
    )
    with pytest.raises(ProviderCapabilityError) as stale:
        await provider.storage.delete(
            created.external_id,
            MutationContext("delete-key", VersionPrecondition(version="stale")),
        )
    assert stale.value.category is CanonicalErrorCategory.CONFLICT
