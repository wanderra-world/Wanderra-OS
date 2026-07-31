"""Shared adapter conformance tests for the H2-05 SDK boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.provider_capabilities.calendar import (
    CalendarEventCreate,
    CalendarEventPatch,
    CalendarListRequest,
)
from app.provider_capabilities.common import (
    CapabilityRegistry,
    MutationContext,
    PageRequest,
    ProviderCapabilityError,
    VersionPrecondition,
)
from app.provider_capabilities.email import (
    EmailListRequest,
    EmailMessageCreate,
    EmailSearchRequest,
)
from app.provider_capabilities.storage import (
    StorageListRequest,
    StorageObjectCreate,
    StorageObjectPatch,
    StorageSearchRequest,
)
from tests.provider_capabilities.support import DeterministicMockProvider


@pytest.fixture
def provider() -> DeterministicMockProvider:
    return DeterministicMockProvider()


def test_mock_second_provider_passes_capability_discovery(
    provider: DeterministicMockProvider,
) -> None:
    registry = CapabilityRegistry()
    registry.register(provider.provider_key, provider.capabilities)
    negotiated = registry.negotiate(
        provider.provider_key,
        {"email": (1,), "calendar": (1,), "storage": (1,)},
    )
    assert negotiated.versions == {"email": 1, "calendar": 1, "storage": 1}


@pytest.mark.asyncio
async def test_email_port_conformance(provider: DeterministicMockProvider) -> None:
    port = provider.email
    page = await port.list_messages(EmailListRequest(page=PageRequest(limit=10)))
    assert [item.external_id for item in page.items] == ["mail-1"]
    assert (await port.search_messages(EmailSearchRequest("atlas"))).items == page.items
    assert (await port.list_unread(EmailListRequest())).items == page.items
    draft = await port.create_draft(
        EmailMessageCreate(to=("recipient@example.test",), subject="Draft", body_text="Body"),
        MutationContext("draft-1"),
    )
    assert draft.subject == "Draft"
    sent = await port.send_message(
        EmailMessageCreate(to=("recipient@example.test",), subject="Sent", body_text="Body"),
        MutationContext("send-1"),
    )
    assert (await port.send_message(
        EmailMessageCreate(to=("recipient@example.test",), subject="Sent", body_text="Body"),
        MutationContext("send-1"),
    )) == sent
    assert (await port.profile()).email_address == "user@mock.example"


@pytest.mark.asyncio
async def test_calendar_port_conformance(provider: DeterministicMockProvider) -> None:
    port = provider.calendar
    event = await port.create_event(
        CalendarEventCreate(
            calendar_external_id="primary",
            summary="Atlas",
            start=datetime(2026, 8, 1, 15, tzinfo=UTC),
            end=datetime(2026, 8, 1, 15, 30, tzinfo=UTC),
        ),
        MutationContext("event-create-1"),
    )
    assert (await port.list_events(CalendarListRequest())).items == (event,)
    updated = await port.update_event(
        event.external_id,
        CalendarEventPatch(summary="Atlas moved"),
        MutationContext("event-update-1", VersionPrecondition(version=event.version)),
    )
    assert updated.summary == "Atlas moved"
    await port.delete_event(
        event.external_id,
        MutationContext("event-delete-1", VersionPrecondition(version=updated.version)),
    )
    assert (await port.list_events(CalendarListRequest())).items == ()


@pytest.mark.asyncio
async def test_storage_port_conformance(provider: DeterministicMockProvider) -> None:
    port = provider.storage
    created = await port.upload(
        StorageObjectCreate("atlas.txt", b"hello", "text/plain"),
        MutationContext("upload-1"),
    )
    assert (await port.list_objects(StorageListRequest())).items == (created,)
    assert (await port.search_objects(StorageSearchRequest("atlas"))).items == (created,)
    assert await port.read_metadata(created.external_id) == created
    assert (await port.download(created.external_id)).content == b"hello"
    assert (await port.read_text(created.external_id)).text == "hello"
    updated = await port.update_metadata(
        created.external_id,
        StorageObjectPatch(name="renamed.txt"),
        MutationContext("metadata-1", VersionPrecondition(version=created.version)),
    )
    replaced = await port.update_content(
        created.external_id,
        b"updated",
        "text/plain",
        MutationContext("content-1", VersionPrecondition(version=updated.version)),
    )
    assert (await port.download(created.external_id)).content == b"updated"
    await port.delete(
        created.external_id,
        MutationContext("delete-1", VersionPrecondition(version=replaced.version)),
    )
    with pytest.raises(ProviderCapabilityError):
        await port.read_metadata(created.external_id)


@pytest.mark.asyncio
async def test_mutation_replay_with_changed_input_fails_closed(
    provider: DeterministicMockProvider,
) -> None:
    context = MutationContext("same-key")
    await provider.email.send_message(
        EmailMessageCreate(to=("one@example.test",), subject="One", body_text="One"),
        context,
    )
    with pytest.raises(ProviderCapabilityError, match="idempotency"):
        await provider.email.send_message(
            EmailMessageCreate(to=("two@example.test",), subject="Two", body_text="Two"),
            context,
        )

