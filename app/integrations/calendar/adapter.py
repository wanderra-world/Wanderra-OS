"""Google Calendar adapter confined to the integration SDK boundary."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Protocol

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.calendar_capability.contracts import CalendarResourceObserver
from app.capability_routing.credentials import ManagedConnectionCredentialLoader
from app.provider_capabilities.calendar import (
    CalendarAttendee,
    CalendarEvent,
    CalendarEventCreate,
    CalendarEventPatch,
    CalendarListRequest,
    CalendarMoment,
)
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    ExtensionEnvelope,
    MutationContext,
    OpaqueCursor,
    Page,
    ProviderCapabilityError,
    VersionPrecondition,
)


class CalendarApi(Protocol):
    async def event_page(
        self,
        *,
        calendar_id: str,
        time_min: str | None,
        time_max: str | None,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]: ...

    async def event(
        self, calendar_id: str, external_id: str
    ) -> dict[str, object]: ...

    async def create(
        self, calendar_id: str, body: dict[str, object]
    ) -> dict[str, object]: ...

    async def update(
        self,
        calendar_id: str,
        external_id: str,
        body: dict[str, object],
        precondition: str,
    ) -> dict[str, object]: ...

    async def delete(
        self, calendar_id: str, external_id: str, precondition: str
    ) -> None: ...


class GoogleCalendarApi:
    """Async façade around the supported Calendar SDK resource."""

    def __init__(self, resource: object) -> None:
        self._resource = resource

    def _events(self):
        return self._resource.events()  # type: ignore[attr-defined,no-any-return]

    async def event_page(
        self,
        *,
        calendar_id: str,
        time_min: str | None,
        time_max: str | None,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        arguments: dict[str, object] = {
            "calendarId": calendar_id,
            "maxResults": limit,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min is not None:
            arguments["timeMin"] = time_min
        if time_max is not None:
            arguments["timeMax"] = time_max
        if cursor is not None:
            arguments["pageToken"] = cursor
        return await asyncio.to_thread(
            lambda: self._events().list(**arguments).execute()
        )

    async def event(
        self, calendar_id: str, external_id: str
    ) -> dict[str, object]:
        return await asyncio.to_thread(
            lambda: self._events()
            .get(calendarId=calendar_id, eventId=external_id)
            .execute()
        )

    async def create(
        self, calendar_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        return await asyncio.to_thread(
            lambda: self._events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )

    async def update(
        self,
        calendar_id: str,
        external_id: str,
        body: dict[str, object],
        precondition: str,
    ) -> dict[str, object]:
        request = self._events().patch(
            calendarId=calendar_id, eventId=external_id, body=body
        )
        request.headers["If-Match"] = precondition
        return await asyncio.to_thread(request.execute)

    async def delete(
        self, calendar_id: str, external_id: str, precondition: str
    ) -> None:
        request = self._events().delete(
            calendarId=calendar_id, eventId=external_id
        )
        request.headers["If-Match"] = precondition
        await asyncio.to_thread(request.execute)


async def build_google_calendar_api(serialized_credential: bytes) -> CalendarApi:
    values = json.loads(serialized_credential)
    credentials = Credentials.from_authorized_user_info(values)
    resource = await asyncio.to_thread(
        build,
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )
    return GoogleCalendarApi(resource)


class CalendarCredentialLoader(Protocol):
    async def load(self) -> bytes: ...


class CalendarApiBuilder(Protocol):
    async def __call__(self, serialized_credential: bytes) -> CalendarApi: ...


class GoogleCalendarManagedPortFactory:
    def __init__(
        self,
        credentials: CalendarCredentialLoader,
        builder: CalendarApiBuilder,
        observer: CalendarResourceObserver | None = None,
    ) -> None:
        self._credentials = credentials
        self._builder = builder
        self._observer = observer

    async def canonical_port(self) -> GoogleCalendarAdapter:
        serialized = await self._credentials.load()
        return GoogleCalendarAdapter(
            await self._builder(serialized), self._observer
        )


ManagedCalendarCredentialLoader = ManagedConnectionCredentialLoader


class GoogleCalendarAdapter:
    def __init__(
        self,
        api: CalendarApi,
        observer: CalendarResourceObserver | None = None,
    ) -> None:
        self._api = api
        self._observer = observer

    async def list_events(
        self, request: CalendarListRequest
    ) -> Page[CalendarEvent]:
        try:
            raw = await self._api.event_page(
                calendar_id=request.calendar_external_id,
                time_min=request.time_min.isoformat()
                if request.time_min is not None
                else None,
                time_max=request.time_max.isoformat()
                if request.time_max is not None
                else None,
                limit=request.page.limit,
                cursor=request.page.cursor.value if request.page.cursor else None,
            )
            items = raw.get("items", [])
            assert isinstance(items, list)
            events: list[CalendarEvent] = []
            for item in items:
                if isinstance(item, dict):
                    events.append(
                        await self._observed(
                            item, request.calendar_external_id
                        )
                    )
            token = raw.get("nextPageToken")
            return Page(
                tuple(events),
                OpaqueCursor(str(token))
                if isinstance(token, str) and token
                else None,
            )
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe_error(error) from error

    async def create_event(
        self, event: CalendarEventCreate, context: MutationContext
    ) -> CalendarEvent:
        del context
        try:
            created = await self._api.create(
                event.calendar_external_id, self._create_body(event)
            )
            external_id = str(created["id"])
            verified = await self._api.event(
                event.calendar_external_id, external_id
            )
            return await self._observed(
                verified, event.calendar_external_id
            )
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe_error(error) from error

    async def update_event(
        self,
        external_id: str,
        changes: CalendarEventPatch,
        context: MutationContext,
    ) -> CalendarEvent:
        precondition = self._precondition(context.precondition)
        try:
            await self._api.update(
                "primary",
                external_id,
                self._patch_body(changes),
                precondition,
            )
            verified = await self._api.event("primary", external_id)
            return await self._observed(verified, "primary")
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe_error(error) from error

    async def delete_event(
        self, external_id: str, context: MutationContext
    ) -> None:
        precondition = self._precondition(context.precondition)
        try:
            await self._api.delete("primary", external_id, precondition)
            try:
                await self._api.event("primary", external_id)
            except ProviderCapabilityError as error:
                if error.category is CanonicalErrorCategory.NOT_FOUND:
                    return
                raise
            raise ProviderCapabilityError(
                CanonicalErrorCategory.CONFLICT,
                "Calendar deletion verification failed.",
            )
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe_error(error) from error

    async def _observed(
        self, raw: dict[str, object], calendar_id: str
    ) -> CalendarEvent:
        event = self._event(raw, calendar_id)
        if self._observer is not None:
            await self._observer.observe(event)
        return event

    @classmethod
    def _event(
        cls, raw: dict[str, object], calendar_id: str
    ) -> CalendarEvent:
        start = raw.get("start")
        end = raw.get("end")
        assert isinstance(start, dict) and isinstance(end, dict)
        attendees = raw.get("attendees", [])
        recurrence = raw.get("recurrence", [])
        sequence = raw.get("sequence")
        version = raw.get("etag") or sequence
        if version is None:
            raise ValueError("Provider event version is required.")
        return CalendarEvent(
            external_id=str(raw["id"]),
            calendar_external_id=calendar_id,
            status=str(raw.get("status", "confirmed")),
            summary=str(raw.get("summary", "")),
            start=cls._moment(start),
            end=cls._moment(end),
            version=str(version),
            description=(
                str(raw["description"])
                if raw.get("description") is not None
                else None
            ),
            location=(
                str(raw["location"])
                if raw.get("location") is not None
                else None
            ),
            attendees=tuple(
                CalendarAttendee(
                    email_address=str(item["email"]),
                    response_status=(
                        str(item["responseStatus"])
                        if item.get("responseStatus") is not None
                        else None
                    ),
                )
                for item in attendees
                if isinstance(item, dict) and "email" in item
            )
            if isinstance(attendees, list)
            else (),
            created_at=cls._timestamp(raw.get("created")),
            updated_at=cls._timestamp(raw.get("updated")),
            recurrence=tuple(str(rule) for rule in recurrence)
            if isinstance(recurrence, list)
            else (),
            extensions=ExtensionEnvelope(
                {"google.calendar/sequence": sequence}
                if isinstance(sequence, int)
                else {}
            ),
        )

    @staticmethod
    def _moment(raw: dict[str, object]) -> CalendarMoment:
        if raw.get("dateTime") is not None:
            return CalendarMoment(
                date_time=datetime.fromisoformat(str(raw["dateTime"])),
                time_zone=(
                    str(raw["timeZone"])
                    if raw.get("timeZone") is not None
                    else None
                ),
            )
        return CalendarMoment(date=date.fromisoformat(str(raw["date"])))

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        return datetime.fromisoformat(str(value)) if value is not None else None

    @classmethod
    def _create_body(cls, event: CalendarEventCreate) -> dict[str, object]:
        body: dict[str, object] = {
            "summary": event.summary,
            "start": cls._write_moment(event.start),
            "end": cls._write_moment(event.end),
        }
        cls._optional(body, "description", event.description)
        cls._optional(body, "location", event.location)
        if event.attendees:
            body["attendees"] = [{"email": value} for value in event.attendees]
        if event.recurrence:
            body["recurrence"] = list(event.recurrence)
        return body

    @classmethod
    def _patch_body(cls, changes: CalendarEventPatch) -> dict[str, object]:
        body: dict[str, object] = {}
        cls._optional(body, "summary", changes.summary)
        cls._optional(body, "description", changes.description)
        cls._optional(body, "location", changes.location)
        if changes.start is not None:
            body["start"] = cls._write_moment(changes.start)
        if changes.end is not None:
            body["end"] = cls._write_moment(changes.end)
        if changes.attendees is not None:
            body["attendees"] = [{"email": value} for value in changes.attendees]
        if changes.recurrence is not None:
            body["recurrence"] = list(changes.recurrence)
        return body

    @staticmethod
    def _write_moment(value: datetime | date) -> dict[str, str]:
        if isinstance(value, datetime):
            if value.utcoffset() is None:
                raise ValueError("Calendar date-time must be timezone-aware.")
            return {"dateTime": value.isoformat()}
        return {"date": value.isoformat()}

    @staticmethod
    def _optional(
        body: dict[str, object], key: str, value: object | None
    ) -> None:
        if value is not None:
            body[key] = value

    @staticmethod
    def _precondition(value: VersionPrecondition | None) -> str:
        if value is None:
            raise ProviderCapabilityError(
                CanonicalErrorCategory.CONFLICT,
                "A calendar version precondition is required.",
            )
        return value.etag or value.version or ""

    @staticmethod
    def _safe_error(error: Exception) -> ProviderCapabilityError:
        response = getattr(error, "resp", None)
        status = getattr(error, "status_code", None) or getattr(
            response, "status", None
        )
        category = {
            400: CanonicalErrorCategory.INVALID_INPUT,
            401: CanonicalErrorCategory.AUTHENTICATION,
            403: CanonicalErrorCategory.AUTHORIZATION,
            404: CanonicalErrorCategory.NOT_FOUND,
            409: CanonicalErrorCategory.CONFLICT,
            412: CanonicalErrorCategory.CONFLICT,
            429: CanonicalErrorCategory.RATE_LIMIT,
        }.get(status, CanonicalErrorCategory.TRANSIENT)
        return ProviderCapabilityError(
            category, "Calendar provider operation failed."
        )
