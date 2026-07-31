"""Deterministic in-memory adapter used by the shared conformance kit."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, TypeVar

from app.provider_capabilities.calendar import (
    CalendarEvent,
    CalendarEventCreate,
    CalendarEventPatch,
    CalendarListRequest,
    CalendarMoment,
)
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    CapabilityDescriptor,
    MutationContext,
    Page,
    ProviderCapabilityError,
)
from app.provider_capabilities.email import (
    EmailAddress,
    EmailListRequest,
    EmailMessage,
    EmailMessageCreate,
    EmailProfile,
    EmailSearchRequest,
)
from app.provider_capabilities.storage import (
    StorageContent,
    StorageListRequest,
    StorageObject,
    StorageObjectCreate,
    StorageObjectPatch,
    StorageSearchRequest,
    StorageText,
)

R = TypeVar("R")


def _fingerprint(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


class _ReplayGuard:
    def __init__(self) -> None:
        self._outcomes: dict[str, tuple[str, Any]] = {}

    def execute(self, key: str, inputs: object, operation: Callable[[], R]) -> R:
        fingerprint = _fingerprint(inputs)
        existing = self._outcomes.get(key)
        if existing is not None:
            if existing[0] != fingerprint:
                raise ProviderCapabilityError(
                    CanonicalErrorCategory.CONFLICT,
                    "The idempotency key was already used with different input.",
                )
            return existing[1]
        outcome = operation()
        self._outcomes[key] = (fingerprint, outcome)
        return outcome


def _missing() -> ProviderCapabilityError:
    return ProviderCapabilityError(
        CanonicalErrorCategory.NOT_FOUND,
        "The requested resource was not found.",
    )


def _moment(value: datetime | date) -> CalendarMoment:
    if isinstance(value, datetime):
        return CalendarMoment(date_time=value)
    return CalendarMoment(date=value)


class _EmailMock:
    def __init__(self) -> None:
        self._guard = _ReplayGuard()
        self._messages = [
            EmailMessage(
                external_id="mail-1",
                thread_external_id="thread-1",
                sender=EmailAddress("sender@mock.example"),
                recipients=(EmailAddress("user@mock.example"),),
                subject="Atlas message",
                body_text="Deterministic content",
                labels=("unread",),
                received_at=datetime(2026, 7, 31, tzinfo=UTC),
                version="1",
            )
        ]
        self._sequence = 1

    async def profile(self) -> EmailProfile:
        return EmailProfile("user@mock.example", "Mock User")

    async def list_messages(self, request: EmailListRequest) -> Page[EmailMessage]:
        return Page(tuple(self._messages[: request.page.limit]))

    async def list_unread(self, request: EmailListRequest) -> Page[EmailMessage]:
        unread = tuple(item for item in self._messages if "unread" in item.labels)
        return Page(unread[: request.page.limit])

    async def search_messages(self, request: EmailSearchRequest) -> Page[EmailMessage]:
        query = request.query.casefold()
        matches = tuple(
            item
            for item in self._messages
            if query in item.subject.casefold() or query in item.body_text.casefold()
        )
        return Page(matches[: request.page.limit])

    def _create(self, message: EmailMessageCreate, label: str) -> EmailMessage:
        self._sequence += 1
        created = EmailMessage(
            external_id=f"mail-{self._sequence}",
            thread_external_id=f"thread-{self._sequence}",
            sender=EmailAddress("user@mock.example"),
            recipients=tuple(EmailAddress(address) for address in message.to),
            subject=message.subject,
            body_text=message.body_text,
            labels=(label,),
            received_at=datetime(2026, 7, 31, 12, tzinfo=UTC),
            version="1",
        )
        self._messages.append(created)
        return created

    async def create_draft(
        self, message: EmailMessageCreate, context: MutationContext
    ) -> EmailMessage:
        return self._guard.execute(
            context.idempotency_key,
            ("draft", message),
            lambda: self._create(message, "draft"),
        )

    async def send_message(
        self, message: EmailMessageCreate, context: MutationContext
    ) -> EmailMessage:
        return self._guard.execute(
            context.idempotency_key,
            ("send", message),
            lambda: self._create(message, "sent"),
        )


class _CalendarMock:
    def __init__(self) -> None:
        self._guard = _ReplayGuard()
        self._events: dict[str, CalendarEvent] = {}
        self._sequence = 0

    async def list_events(self, request: CalendarListRequest) -> Page[CalendarEvent]:
        events = tuple(
            event
            for event in self._events.values()
            if event.calendar_external_id == request.calendar_external_id
        )
        return Page(events[: request.page.limit])

    async def create_event(
        self, event: CalendarEventCreate, context: MutationContext
    ) -> CalendarEvent:
        def create() -> CalendarEvent:
            self._sequence += 1
            created = CalendarEvent(
                external_id=f"event-{self._sequence}",
                calendar_external_id=event.calendar_external_id,
                status="confirmed",
                summary=event.summary,
                start=_moment(event.start),
                end=_moment(event.end),
                version="1",
                description=event.description,
                location=event.location,
            )
            self._events[created.external_id] = created
            return created

        return self._guard.execute(context.idempotency_key, ("create", event), create)

    def _current(self, external_id: str, context: MutationContext) -> CalendarEvent:
        current = self._events.get(external_id)
        if current is None:
            raise _missing()
        if context.precondition is None or context.precondition.version != current.version:
            raise ProviderCapabilityError(
                CanonicalErrorCategory.CONFLICT,
                "The resource version precondition did not match.",
            )
        return current

    async def update_event(
        self,
        external_id: str,
        changes: CalendarEventPatch,
        context: MutationContext,
    ) -> CalendarEvent:
        def update() -> CalendarEvent:
            current = self._current(external_id, context)
            updated = replace(
                current,
                summary=changes.summary or current.summary,
                start=_moment(changes.start) if changes.start is not None else current.start,
                end=_moment(changes.end) if changes.end is not None else current.end,
                description=changes.description
                if changes.description is not None
                else current.description,
                location=changes.location if changes.location is not None else current.location,
                version=str(int(current.version) + 1),
            )
            self._events[external_id] = updated
            return updated

        return self._guard.execute(
            context.idempotency_key, ("update", external_id, changes, context.precondition), update
        )

    async def delete_event(self, external_id: str, context: MutationContext) -> None:
        def delete() -> None:
            self._current(external_id, context)
            del self._events[external_id]

        self._guard.execute(
            context.idempotency_key, ("delete", external_id, context.precondition), delete
        )


class _StorageMock:
    def __init__(self) -> None:
        self._guard = _ReplayGuard()
        self._objects: dict[str, tuple[StorageObject, bytes]] = {}
        self._sequence = 0

    async def list_objects(self, request: StorageListRequest) -> Page[StorageObject]:
        return Page(tuple(item[0] for item in self._objects.values())[: request.page.limit])

    async def search_objects(self, request: StorageSearchRequest) -> Page[StorageObject]:
        query = request.query.casefold()
        items = tuple(
            item[0] for item in self._objects.values() if query in item[0].name.casefold()
        )
        return Page(items[: request.page.limit])

    def _current(self, external_id: str) -> tuple[StorageObject, bytes]:
        current = self._objects.get(external_id)
        if current is None:
            raise _missing()
        return current

    def _checked(
        self, external_id: str, context: MutationContext
    ) -> tuple[StorageObject, bytes]:
        current = self._current(external_id)
        if context.precondition is None or context.precondition.version != current[0].version:
            raise ProviderCapabilityError(
                CanonicalErrorCategory.CONFLICT,
                "The resource version precondition did not match.",
            )
        return current

    async def read_metadata(self, external_id: str) -> StorageObject:
        return self._current(external_id)[0]

    async def download(self, external_id: str) -> StorageContent:
        metadata, content = self._current(external_id)
        return StorageContent(metadata, content, metadata.media_type)

    async def read_text(self, external_id: str) -> StorageText:
        metadata, content = self._current(external_id)
        if not metadata.media_type.startswith("text/"):
            raise ProviderCapabilityError(
                CanonicalErrorCategory.UNSUPPORTED_CAPABILITY,
                "Text projection is unavailable for this media type.",
            )
        return StorageText(metadata, content.decode())

    async def upload(
        self, item: StorageObjectCreate, context: MutationContext
    ) -> StorageObject:
        def upload() -> StorageObject:
            self._sequence += 1
            metadata = StorageObject(
                external_id=f"object-{self._sequence}",
                name=item.name,
                media_type=item.media_type,
                size=len(item.content),
                version="1",
                modified_at=datetime(2026, 7, 31, tzinfo=UTC),
                parent_external_ids=(item.parent_external_id,)
                if item.parent_external_id
                else (),
                description=item.description,
            )
            self._objects[metadata.external_id] = (metadata, item.content)
            return metadata

        return self._guard.execute(context.idempotency_key, ("upload", item), upload)

    async def update_metadata(
        self,
        external_id: str,
        changes: StorageObjectPatch,
        context: MutationContext,
    ) -> StorageObject:
        def update() -> StorageObject:
            current, content = self._checked(external_id, context)
            updated = replace(
                current,
                name=changes.name or current.name,
                description=changes.description
                if changes.description is not None
                else current.description,
                version=str(int(current.version) + 1),
            )
            self._objects[external_id] = (updated, content)
            return updated

        return self._guard.execute(
            context.idempotency_key,
            ("metadata", external_id, changes, context.precondition),
            update,
        )

    async def update_content(
        self,
        external_id: str,
        content: bytes,
        media_type: str,
        context: MutationContext,
    ) -> StorageObject:
        def update() -> StorageObject:
            current, _ = self._checked(external_id, context)
            updated = replace(
                current,
                media_type=media_type,
                size=len(content),
                version=str(int(current.version) + 1),
            )
            self._objects[external_id] = (updated, content)
            return updated

        return self._guard.execute(
            context.idempotency_key,
            ("content", external_id, content, media_type, context.precondition),
            update,
        )

    async def delete(self, external_id: str, context: MutationContext) -> None:
        def delete() -> None:
            self._checked(external_id, context)
            del self._objects[external_id]

        self._guard.execute(
            context.idempotency_key, ("delete", external_id, context.precondition), delete
        )


class DeterministicMockProvider:
    """Second-provider proof that exercises only canonical contracts."""

    provider_key = "mock.example"
    capabilities = (
        CapabilityDescriptor(
            "email",
            1,
            ("profile", "list", "unread", "search", "draft", "send"),
        ),
        CapabilityDescriptor("calendar", 1, ("list", "create", "update", "delete")),
        CapabilityDescriptor(
            "storage",
            1,
            (
                "list",
                "search",
                "metadata",
                "download",
                "read_text",
                "upload",
                "update_metadata",
                "update_content",
                "delete",
            ),
        ),
    )

    def __init__(self) -> None:
        self.email = _EmailMock()
        self.calendar = _CalendarMock()
        self.storage = _StorageMock()
