"""Google Calendar OAuth and event operations."""

import asyncio
import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.integrations.google_errors import execute_google_request
from app.integrations.google_oauth import (
    CALENDAR_SCOPES,
    accepted_incremental_scopes,
)
from app.models.calendar import CalendarCredential, CalendarOAuthState

SCOPES = sorted(CALENDAR_SCOPES)


class CalendarConfigurationError(RuntimeError):
    pass


class CalendarNotConnectedError(RuntimeError):
    pass


class CalendarService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        if not self._has_oauth_client() or self.settings.gmail_credentials_encryption_key is None:
            raise CalendarConfigurationError(
                "Google OAuth and credential encryption settings are required."
            )
        key = self.settings.gmail_credentials_encryption_key.get_secret_value().encode()
        self.fernet = Fernet(key)

    def _has_oauth_client(self) -> bool:
        return Path(self.settings.google_oauth_client_secret_file).is_file() or bool(
            self.settings.google_oauth_client_id and self.settings.google_oauth_client_secret
        )

    def _flow(self, state: str | None = None) -> Flow:
        options = {
            "scopes": SCOPES,
            "state": state,
            # Reuse the callback already registered for the existing Google client.
            "redirect_uri": self.settings.google_oauth_redirect_uri,
            "autogenerate_code_verifier": True,
        }
        client_file = Path(self.settings.google_oauth_client_secret_file)
        if client_file.is_file():
            return Flow.from_client_secrets_file(str(client_file), **options)
        return Flow.from_client_config(
            {
                "web": {
                    "client_id": self.settings.google_oauth_client_id,
                    "client_secret": self.settings.google_oauth_client_secret.get_secret_value(),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.settings.google_oauth_redirect_uri],
                }
            },
            **options,
        )

    async def authorization_url(self, user_id: uuid.UUID) -> str:
        state = (
            base64.urlsafe_b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes)
            .decode()
            .rstrip("=")
        )
        flow = self._flow(state)
        url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        if flow.code_verifier is None:
            raise CalendarConfigurationError("Google OAuth did not create a PKCE verifier.")
        self.session.add(
            CalendarOAuthState(
                state=state,
                user_id=user_id,
                code_verifier=flow.code_verifier,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await self.session.commit()
        return url

    async def complete_oauth(
        self, state: str, code: str, returned_scope: str | None = None
    ) -> uuid.UUID:
        oauth_state = await self.session.get(CalendarOAuthState, state)
        if oauth_state is None or oauth_state.expires_at < datetime.now(UTC):
            raise CalendarNotConnectedError("OAuth state is invalid or expired.")
        flow = self._flow(state)
        flow.code_verifier = oauth_state.code_verifier
        try:
            accepted = accepted_incremental_scopes(returned_scope, CALENDAR_SCOPES)
        except ValueError as error:
            raise CalendarNotConnectedError(str(error)) from error
        if accepted is not None:
            # Google returns previously granted Gmail scopes during incremental
            # authorization. Align the session before oauthlib validates the token.
            flow.oauth2session.scope = accepted
        await asyncio.to_thread(flow.fetch_token, code=code)
        await self._save_credentials(oauth_state.user_id, flow.credentials)
        await self.session.delete(oauth_state)
        await self.session.commit()
        return oauth_state.user_id

    async def _save_credentials(self, user_id: uuid.UUID, credentials: Credentials) -> None:
        payload = self.fernet.encrypt(credentials.to_json().encode()).decode()
        record = await self.session.get(CalendarCredential, user_id)
        if record is None:
            self.session.add(CalendarCredential(user_id=user_id, encrypted_payload=payload))
        else:
            record.encrypted_payload = payload

    async def _client(self, user_id: uuid.UUID):
        record = await self.session.get(CalendarCredential, user_id)
        if record is None:
            raise CalendarNotConnectedError(
                "Connect Google Calendar through OAuth before accessing events."
            )
        raw = self.fernet.decrypt(record.encrypted_payload.encode())
        credentials = Credentials.from_authorized_user_info(json.loads(raw))
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request

            await asyncio.to_thread(credentials.refresh, Request())
            await self._save_credentials(user_id, credentials)
            await self.session.commit()
        return await execute_google_request(
            lambda: build(
                "calendar",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )
        )

    async def list_events(
        self,
        user_id: uuid.UUID,
        calendar_id: str = "primary",
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        client = await self._client(user_id)
        options = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min is not None:
            options["timeMin"] = time_min.isoformat()
        if time_max is not None:
            options["timeMax"] = time_max.isoformat()
        result = await execute_google_request(
            lambda: client.events().list(**options).execute()
        )
        return [self._event_view(event) for event in result.get("items", [])]

    async def create_event(
        self, user_id: uuid.UUID, event: dict, calendar_id: str = "primary"
    ) -> dict:
        client = await self._client(user_id)
        result = await execute_google_request(
            lambda: client.events().insert(calendarId=calendar_id, body=event).execute()
        )
        return self._event_view(result)

    async def update_event(
        self,
        user_id: uuid.UUID,
        event_id: str,
        changes: dict,
        calendar_id: str = "primary",
    ) -> dict:
        client = await self._client(user_id)
        result = await execute_google_request(
            lambda: client.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=changes)
            .execute()
        )
        return self._event_view(result)

    async def delete_event(
        self, user_id: uuid.UUID, event_id: str, calendar_id: str = "primary"
    ) -> None:
        client = await self._client(user_id)
        await execute_google_request(
            lambda: client.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        )

    async def test_connection(self, user_id: uuid.UUID) -> str:
        client = await self._client(user_id)
        calendar = await execute_google_request(
            lambda: client.calendars().get(calendarId="primary").execute()
        )
        return calendar.get("summary", "primary")

    @staticmethod
    def _event_view(event: dict) -> dict:
        return {
            key: event[key]
            for key in (
                "id",
                "status",
                "htmlLink",
                "summary",
                "description",
                "location",
                "start",
                "end",
                "attendees",
                "creator",
                "organizer",
                "created",
                "updated",
            )
            if key in event
        }
