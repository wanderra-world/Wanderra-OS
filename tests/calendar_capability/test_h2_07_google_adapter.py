from __future__ import annotations

from datetime import date, datetime

import pytest

from app.integrations.calendar.adapter import GoogleCalendarAdapter
from app.provider_capabilities.calendar import (
    CalendarEventCreate,
    CalendarEventPatch,
    CalendarListRequest,
)
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    MutationContext,
    OpaqueCursor,
    PageRequest,
    ProviderCapabilityError,
    VersionPrecondition,
)


class FakeCalendarApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.deleted = False

    async def event_page(
        self,
        *,
        calendar_id: str,
        time_min: str | None,
        time_max: str | None,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        self.calls.append(
            ("page", (calendar_id, time_min, time_max, limit, cursor))
        )
        return {"items": [self.raw_event()], "nextPageToken": "next"}

    async def event(
        self, calendar_id: str, external_id: str
    ) -> dict[str, object]:
        self.calls.append(("get", (calendar_id, external_id)))
        if self.deleted:
            raise ProviderCapabilityError(
                CanonicalErrorCategory.NOT_FOUND, "Event not found."
            )
        return self.raw_event(external_id)

    async def create(
        self, calendar_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        self.calls.append(("create", (calendar_id, body)))
        return self.raw_event("created")

    async def update(
        self,
        calendar_id: str,
        external_id: str,
        body: dict[str, object],
        precondition: str,
    ) -> dict[str, object]:
        self.calls.append(
            ("update", (calendar_id, external_id, body, precondition))
        )
        return self.raw_event(external_id)

    async def delete(
        self, calendar_id: str, external_id: str, precondition: str
    ) -> None:
        self.calls.append(
            ("delete", (calendar_id, external_id, precondition))
        )
        self.deleted = True

    @staticmethod
    def raw_event(external_id: str = "event-1") -> dict[str, object]:
        return {
            "id": external_id,
            "status": "confirmed",
            "summary": "Atlas",
            "description": "Architecture",
            "location": "Stockholm",
            "etag": '"version-7"',
            "sequence": 7,
            "start": {
                "dateTime": "2026-08-01T15:00:00+02:00",
                "timeZone": "Europe/Stockholm",
            },
            "end": {
                "dateTime": "2026-08-01T15:30:00+02:00",
                "timeZone": "Europe/Stockholm",
            },
            "attendees": [
                {"email": "user@example.com", "responseStatus": "accepted"}
            ],
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=2"],
            "created": "2026-07-31T12:00:00Z",
            "updated": "2026-07-31T12:01:00Z",
        }


@pytest.mark.asyncio
async def test_adapter_preserves_timezone_recurrence_attendees_and_cursor() -> None:
    api = FakeCalendarApi()
    adapter = GoogleCalendarAdapter(api)
    page = await adapter.list_events(
        CalendarListRequest(
            time_min=datetime.fromisoformat("2026-08-01T00:00:00+02:00"),
            page=PageRequest(limit=25, cursor=OpaqueCursor("prior")),
        )
    )

    event = page.items[0]
    assert event.start.date_time.isoformat() == "2026-08-01T15:00:00+02:00"
    assert event.start.time_zone == "Europe/Stockholm"
    assert event.recurrence == ("RRULE:FREQ=WEEKLY;COUNT=2",)
    assert event.attendees[0].response_status == "accepted"
    assert event.version == '"version-7"'
    assert event.extensions.values["google.calendar/sequence"] == 7
    assert page.next_cursor == OpaqueCursor("next")


@pytest.mark.asyncio
async def test_adapter_round_trips_all_day_and_timed_mutations_with_verification() -> None:
    api = FakeCalendarApi()
    adapter = GoogleCalendarAdapter(api)
    created = await adapter.create_event(
        CalendarEventCreate(
            calendar_external_id="primary",
            summary="Atlas",
            start=date(2026, 8, 2),
            end=date(2026, 8, 3),
            recurrence=("RRULE:FREQ=DAILY;COUNT=2",),
        ),
        MutationContext("create-1"),
    )
    assert created.external_id == "created"
    create_body = api.calls[0][1][1]
    assert create_body["start"] == {"date": "2026-08-02"}
    assert create_body["recurrence"] == ["RRULE:FREQ=DAILY;COUNT=2"]
    assert api.calls[1] == ("get", ("primary", "created"))

    await adapter.update_event(
        "event-1",
        CalendarEventPatch(
            start=datetime.fromisoformat("2026-08-01T16:00:00+02:00")
        ),
        MutationContext(
            "update-1", VersionPrecondition(etag='"version-7"')
        ),
    )
    assert api.calls[2][1][-1] == '"version-7"'
    assert api.calls[3] == ("get", ("primary", "event-1"))

    await adapter.delete_event(
        "event-1",
        MutationContext(
            "delete-1", VersionPrecondition(etag='"version-7"')
        ),
    )
    assert api.calls[4][1][-1] == '"version-7"'
    assert api.calls[5] == ("get", ("primary", "event-1"))


@pytest.mark.asyncio
async def test_adapter_rejects_blind_update_and_maps_safe_errors() -> None:
    adapter = GoogleCalendarAdapter(FakeCalendarApi())
    with pytest.raises(ProviderCapabilityError) as caught:
        await adapter.update_event(
            "event-1",
            CalendarEventPatch(summary="Changed"),
            MutationContext("update-without-version"),
        )
    assert caught.value.category is CanonicalErrorCategory.CONFLICT

    class Failing(FakeCalendarApi):
        async def event_page(self, **_: object) -> dict[str, object]:
            raise RuntimeError("secret provider diagnostic")

    with pytest.raises(ProviderCapabilityError) as failure:
        await GoogleCalendarAdapter(Failing()).list_events(CalendarListRequest())
    assert failure.value.category is CanonicalErrorCategory.TRANSIENT
    assert "secret provider diagnostic" not in str(failure.value)
