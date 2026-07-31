from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.integrations.gmail.adapter import GmailEmailAdapter
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    MutationContext,
    OpaqueCursor,
    PageRequest,
    ProviderCapabilityError,
)
from app.provider_capabilities.email import (
    EmailListRequest,
    EmailMessageCreate,
    EmailSearchRequest,
)


class FakeGmailApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def profile(self) -> dict[str, object]:
        return {"emailAddress": "atlas@example.com"}

    async def message_page(
        self, *, query: str | None, limit: int, cursor: str | None
    ) -> dict[str, object]:
        self.calls.append(("page", (query, limit, cursor)))
        return {"messages": [{"id": "m-1"}], "nextPageToken": "next"}

    async def message(self, external_id: str) -> dict[str, object]:
        self.calls.append(("message", external_id))
        return {
            "id": external_id,
            "threadId": "t-1",
            "labelIds": ["INBOX"],
            "internalDate": "1735689600000",
            "historyId": "7",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Atlas <atlas@example.com>"},
                    {"name": "To", "value": "user@example.com"},
                    {"name": "Subject", "value": "Canonical"},
                ],
                "mimeType": "text/plain",
                "body": {"data": "SGVsbG8"},
            },
        }

    async def create_draft(self, raw_message: str) -> dict[str, object]:
        return {"message": await self.message("draft-1")}

    async def send(self, raw_message: str) -> dict[str, object]:
        return await self.message("sent-1")


@pytest.mark.asyncio
async def test_gmail_adapter_translates_reads_cursors_and_extensions() -> None:
    api = FakeGmailApi()
    adapter = GmailEmailAdapter(api)

    assert (await adapter.profile()).email_address == "atlas@example.com"
    page = await adapter.list_messages(
        EmailListRequest(PageRequest(limit=12, cursor=OpaqueCursor("prior")))
    )
    assert page.next_cursor == OpaqueCursor("next")
    assert page.items[0].subject == "Canonical"
    assert page.items[0].body_text == "Hello"
    assert page.items[0].received_at == datetime(2025, 1, 1, tzinfo=UTC)
    assert page.items[0].extensions.values["google.gmail/history_id"] == "7"
    assert api.calls[0] == ("page", (None, 12, "prior"))

    await adapter.list_unread(EmailListRequest())
    await adapter.search_messages(EmailSearchRequest("from:openai.com"))
    assert api.calls[2][1][0] == "is:unread"
    assert api.calls[4][1][0] == "from:openai.com"


@pytest.mark.asyncio
async def test_gmail_adapter_maps_provider_failures_to_safe_canonical_error() -> None:
    class Failing(FakeGmailApi):
        async def profile(self) -> dict[str, object]:
            raise RuntimeError("secret token must not escape")

    with pytest.raises(ProviderCapabilityError) as caught:
        await GmailEmailAdapter(Failing()).profile()
    assert caught.value.category is CanonicalErrorCategory.TRANSIENT
    assert "secret token" not in str(caught.value)


@pytest.mark.asyncio
async def test_gmail_adapter_translates_mutations_without_sdk_objects() -> None:
    adapter = GmailEmailAdapter(FakeGmailApi())
    create = EmailMessageCreate(
        to=("user@example.com",), subject="Atlas", body_text="Working"
    )
    draft = await adapter.create_draft(create, MutationContext("draft-key"))
    sent = await adapter.send_message(create, MutationContext("send-key"))
    assert draft.external_id == "draft-1"
    assert sent.external_id == "sent-1"


@pytest.mark.asyncio
async def test_gmail_adapter_observes_exercised_message_resources() -> None:
    class Observer:
        def __init__(self) -> None:
            self.ids: list[str] = []

        async def observe(self, message) -> None:
            self.ids.append(message.external_id)

    observer = Observer()
    adapter = GmailEmailAdapter(FakeGmailApi(), observer)
    await adapter.list_messages(EmailListRequest())
    assert observer.ids == ["m-1"]
