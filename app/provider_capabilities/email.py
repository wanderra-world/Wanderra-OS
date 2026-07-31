"""Provider-neutral email capability contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.provider_capabilities.common import (
    EMPTY_EXTENSIONS,
    ExtensionEnvelope,
    MutationContext,
    Page,
    PageRequest,
)


@dataclass(frozen=True, slots=True)
class EmailAddress:
    address: str
    display_name: str | None = None

    def __post_init__(self) -> None:
        if "@" not in self.address:
            raise ValueError("A canonical email address is required.")


@dataclass(frozen=True, slots=True)
class EmailProfile:
    email_address: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class EmailMessage:
    external_id: str
    thread_external_id: str | None
    sender: EmailAddress
    recipients: tuple[EmailAddress, ...]
    subject: str
    body_text: str
    labels: tuple[str, ...] = ()
    received_at: datetime | None = None
    version: str | None = None
    extensions: ExtensionEnvelope = EMPTY_EXTENSIONS

    def __post_init__(self) -> None:
        if not self.external_id:
            raise ValueError("Stable external message identity is required.")
        if self.received_at is not None and self.received_at.utcoffset() is None:
            raise ValueError("Message timestamp must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class EmailMessageCreate:
    to: tuple[str, ...]
    subject: str
    body_text: str
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.to or not self.subject or not self.body_text:
            raise ValueError("Recipient, subject, and body are required.")


@dataclass(frozen=True, slots=True)
class EmailListRequest:
    page: PageRequest = PageRequest()


@dataclass(frozen=True, slots=True)
class EmailSearchRequest:
    query: str
    page: PageRequest = PageRequest()

    def __post_init__(self) -> None:
        if not self.query:
            raise ValueError("Search query is required.")


class EmailPort(Protocol):
    async def profile(self) -> EmailProfile: ...
    async def list_messages(self, request: EmailListRequest) -> Page[EmailMessage]: ...
    async def list_unread(self, request: EmailListRequest) -> Page[EmailMessage]: ...
    async def search_messages(self, request: EmailSearchRequest) -> Page[EmailMessage]: ...
    async def create_draft(
        self, message: EmailMessageCreate, context: MutationContext
    ) -> EmailMessage: ...
    async def send_message(
        self, message: EmailMessageCreate, context: MutationContext
    ) -> EmailMessage: ...
