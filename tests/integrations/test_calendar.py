from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.api.v1.calendar import CreateEventRequest, EventTime, UpdateEventRequest, _event_body
from app.integrations.calendar.service import CalendarService


def test_calendar_event_request_serializes_google_field_names() -> None:
    request = CreateEventRequest(
        summary="Flight to Stockholm",
        description="Terminal 5",
        start=EventTime(
            date_time=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
            time_zone="Europe/Stockholm",
        ),
        end=EventTime(
            date_time=datetime(2026, 8, 1, 11, 0, tzinfo=UTC),
            time_zone="Europe/Stockholm",
        ),
    )

    assert _event_body(request) == {
        "summary": "Flight to Stockholm",
        "description": "Terminal 5",
        "start": {
            "dateTime": "2026-08-01T09:00:00Z",
            "timeZone": "Europe/Stockholm",
        },
        "end": {
            "dateTime": "2026-08-01T11:00:00Z",
            "timeZone": "Europe/Stockholm",
        },
    }


def test_calendar_event_time_requires_date_or_datetime() -> None:
    with pytest.raises(ValidationError):
        EventTime()

    with pytest.raises(ValidationError):
        EventTime(date="2026-08-01", dateTime="2026-08-01T09:00:00Z")


def test_calendar_update_requires_a_change() -> None:
    with pytest.raises(ValidationError):
        UpdateEventRequest()


def test_calendar_event_view_returns_supported_fields_only() -> None:
    event = CalendarService._event_view(
        {
            "id": "event-1",
            "summary": "Atlas planning",
            "start": {"dateTime": "2026-08-01T09:00:00Z"},
            "end": {"dateTime": "2026-08-01T10:00:00Z"},
            "etag": "private-api-detail",
        }
    )

    assert event == {
        "id": "event-1",
        "summary": "Atlas planning",
        "start": {"dateTime": "2026-08-01T09:00:00Z"},
        "end": {"dateTime": "2026-08-01T10:00:00Z"},
    }
