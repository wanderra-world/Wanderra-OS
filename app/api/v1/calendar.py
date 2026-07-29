import uuid
from datetime import date as Date
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.integrations.calendar.service import (
    CalendarConfigurationError,
    CalendarNotConnectedError,
    CalendarService,
)
from app.integrations.errors import ProviderOperationError

router = APIRouter()


class EventTime(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date_time: datetime | None = Field(None, alias="dateTime")
    date: Date | None = None
    time_zone: str | None = Field(None, alias="timeZone")

    @model_validator(mode="after")
    def exactly_one_time(self):
        if (self.date_time is None) == (self.date is None):
            raise ValueError("Provide exactly one of dateTime or date.")
        return self


class Attendee(BaseModel):
    email: str


class CreateEventRequest(BaseModel):
    summary: str = Field(min_length=1)
    start: EventTime
    end: EventTime
    description: str | None = None
    location: str | None = None
    attendees: list[Attendee] | None = None


class UpdateEventRequest(BaseModel):
    summary: str | None = Field(None, min_length=1)
    start: EventTime | None = None
    end: EventTime | None = None
    description: str | None = None
    location: str | None = None
    attendees: list[Attendee] | None = None

    @model_validator(mode="after")
    def at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        return self


def _service(session: AsyncSession) -> CalendarService:
    return CalendarService(session)


async def _calendar_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CalendarService:
    try:
        return _service(session)
    except CalendarConfigurationError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Google Calendar is not configured."
        ) from error


def _not_connected(error: CalendarNotConnectedError) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, str(error))


def _provider_error(error: ProviderOperationError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


def _event_body(request: BaseModel) -> dict:
    return request.model_dump(by_alias=True, exclude_none=True, mode="json")


@router.get("/oauth/authorize")
async def calendar_authorize(
    service: Annotated[CalendarService, Depends(_calendar_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
) -> dict[str, str]:
    return {"authorization_url": await service.authorization_url(x_user_id)}


@router.get("/events")
async def list_events(
    service: Annotated[CalendarService, Depends(_calendar_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
    calendar_id: str = Query("primary"),
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    limit: int = Query(50, ge=1, le=2500),
):
    try:
        return await service.list_events(
            x_user_id, calendar_id, time_min, time_max, limit
        )
    except CalendarNotConnectedError as error:
        raise _not_connected(error)
    except ProviderOperationError as error:
        raise _provider_error(error)


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    request: CreateEventRequest,
    service: Annotated[CalendarService, Depends(_calendar_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
    calendar_id: str = Query("primary"),
):
    try:
        return await service.create_event(x_user_id, _event_body(request), calendar_id)
    except CalendarNotConnectedError as error:
        raise _not_connected(error)
    except ProviderOperationError as error:
        raise _provider_error(error)


@router.patch("/events/{event_id}")
async def update_event(
    event_id: str,
    request: UpdateEventRequest,
    service: Annotated[CalendarService, Depends(_calendar_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
    calendar_id: str = Query("primary"),
):
    try:
        return await service.update_event(
            x_user_id, event_id, _event_body(request), calendar_id
        )
    except CalendarNotConnectedError as error:
        raise _not_connected(error)
    except ProviderOperationError as error:
        raise _provider_error(error)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    service: Annotated[CalendarService, Depends(_calendar_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
    calendar_id: str = Query("primary"),
) -> Response:
    try:
        await service.delete_event(x_user_id, event_id, calendar_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except CalendarNotConnectedError as error:
        raise _not_connected(error)
    except ProviderOperationError as error:
        raise _provider_error(error)
