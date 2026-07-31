"""Provider-neutral calendar capability contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.provider_capabilities.common import (
    EMPTY_EXTENSIONS,
    ExtensionEnvelope,
    MutationContext,
    Page,
    PageRequest,
)


@dataclass(frozen=True, slots=True)
class CalendarMoment:
    date_time: datetime | None = None
    date: date | None = None
    time_zone: str | None = None

    def __post_init__(self) -> None:
        if (self.date_time is None) == (self.date is None):
            raise ValueError("Provide exactly one timed or all-day value.")
        if self.date_time is not None and self.date_time.utcoffset() is None:
            raise ValueError("Calendar date-time must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class CalendarAttendee:
    email_address: str
    response_status: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    external_id: str
    calendar_external_id: str
    status: str
    summary: str
    start: CalendarMoment
    end: CalendarMoment
    version: str
    description: str | None = None
    location: str | None = None
    attendees: tuple[CalendarAttendee, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None
    extensions: ExtensionEnvelope = EMPTY_EXTENSIONS


@dataclass(frozen=True, slots=True)
class CalendarListRequest:
    calendar_external_id: str = "primary"
    time_min: datetime | None = None
    time_max: datetime | None = None
    page: PageRequest = PageRequest()


@dataclass(frozen=True, slots=True)
class CalendarEventCreate:
    calendar_external_id: str
    summary: str
    start: datetime | date
    end: datetime | date
    description: str | None = None
    location: str | None = None
    attendees: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CalendarEventPatch:
    summary: str | None = None
    start: datetime | date | None = None
    end: datetime | date | None = None
    description: str | None = None
    location: str | None = None
    attendees: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if all(
            value is None
            for value in (
                self.summary,
                self.start,
                self.end,
                self.description,
                self.location,
                self.attendees,
            )
        ):
            raise ValueError("At least one event change is required.")


class CalendarPort(Protocol):
    async def list_events(self, request: CalendarListRequest) -> Page[CalendarEvent]: ...
    async def create_event(
        self, event: CalendarEventCreate, context: MutationContext
    ) -> CalendarEvent: ...
    async def update_event(
        self,
        external_id: str,
        changes: CalendarEventPatch,
        context: MutationContext,
    ) -> CalendarEvent: ...
    async def delete_event(self, external_id: str, context: MutationContext) -> None: ...
