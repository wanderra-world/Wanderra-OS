"""Gmail integration using Google's supported OAuth and API client libraries."""

import asyncio
import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.integrations.google_oauth import GMAIL_SCOPES, accepted_incremental_scopes
from app.memory.service import MemoryService
from app.models.gmail import GmailCredential, GmailOAuthState

SCOPES = sorted(GMAIL_SCOPES)


class GmailConfigurationError(RuntimeError):
    pass


class GmailNotConnectedError(RuntimeError):
    pass


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    sender: str
    recipients: str
    subject: str
    body: str
    labels: list[str]


class GmailService:
    def __init__(self, session: AsyncSession, memory: MemoryService, settings: Settings | None = None) -> None:
        self.session, self.memory, self.settings = session, memory, settings or get_settings()
        if not self._has_oauth_client() or self.settings.gmail_credentials_encryption_key is None:
            raise GmailConfigurationError("Gmail OAuth and credential encryption settings are required.")
        self.fernet = Fernet(self.settings.gmail_credentials_encryption_key.get_secret_value().encode())

    def _flow(self, state: str | None = None) -> Flow:
        client_file = Path(self.settings.google_oauth_client_secret_file)
        if client_file.is_file():
            return Flow.from_client_secrets_file(
                str(client_file),
                scopes=SCOPES,
                state=state,
                redirect_uri=self.settings.google_oauth_redirect_uri,
                autogenerate_code_verifier=True,
            )
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
            scopes=SCOPES,
            state=state,
            redirect_uri=self.settings.google_oauth_redirect_uri,
            autogenerate_code_verifier=True,
        )

    def _has_oauth_client(self) -> bool:
        return Path(self.settings.google_oauth_client_secret_file).is_file() or bool(
            self.settings.google_oauth_client_id and self.settings.google_oauth_client_secret
        )

    async def authorization_url(self, user_id: uuid.UUID) -> str:
        state = base64.urlsafe_b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).decode().rstrip("=")
        flow = self._flow(state)
        url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
        if flow.code_verifier is None:
            raise GmailConfigurationError("Google OAuth did not create a PKCE verifier.")
        self.session.add(GmailOAuthState(state=state, user_id=user_id, code_verifier=flow.code_verifier, expires_at=datetime.now(UTC) + timedelta(minutes=10)))
        await self.session.commit()
        return url

    async def complete_oauth(
        self, state: str, code: str, returned_scope: str | None = None
    ) -> uuid.UUID:
        oauth_state = await self.session.get(GmailOAuthState, state)
        if oauth_state is None or oauth_state.expires_at < datetime.now(UTC):
            raise GmailNotConnectedError("OAuth state is invalid or expired.")
        flow = self._flow(state)
        flow.code_verifier = oauth_state.code_verifier
        try:
            accepted = accepted_incremental_scopes(returned_scope, GMAIL_SCOPES)
        except ValueError as error:
            raise GmailNotConnectedError(str(error)) from error
        if accepted is not None:
            flow.oauth2session.scope = accepted
        await asyncio.to_thread(flow.fetch_token, code=code)
        await self._save_credentials(oauth_state.user_id, flow.credentials)
        await self.session.delete(oauth_state)
        await self.session.commit()
        return oauth_state.user_id

    async def _save_credentials(self, user_id: uuid.UUID, credentials: Credentials) -> None:
        payload = self.fernet.encrypt(credentials.to_json().encode()).decode()
        record = await self.session.get(GmailCredential, user_id)
        if record is None:
            self.session.add(GmailCredential(user_id=user_id, encrypted_payload=payload))
        else:
            record.encrypted_payload = payload

    async def _client(self, user_id: uuid.UUID):
        record = await self.session.get(GmailCredential, user_id)
        if record is None:
            raise GmailNotConnectedError("Connect Gmail through OAuth before accessing the mailbox.")
        credentials = Credentials.from_authorized_user_info(json.loads(self.fernet.decrypt(record.encrypted_payload.encode())))
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request
            await asyncio.to_thread(credentials.refresh, Request())
            await self._save_credentials(user_id, credentials)
            await self.session.commit()
        return await asyncio.to_thread(build, "gmail", "v1", credentials=credentials, cache_discovery=False)

    async def list_messages(self, user_id: uuid.UUID, max_results: int = 20) -> list[GmailMessage]:
        client = await self._client(user_id)
        page = await asyncio.to_thread(lambda: client.users().messages().list(userId="me", maxResults=max_results).execute())
        return [await self.get_message(user_id, item["id"], client) for item in page.get("messages", [])]

    async def get_message(self, user_id: uuid.UUID, message_id: str, client=None) -> GmailMessage:
        client = client or await self._client(user_id)
        raw = await asyncio.to_thread(lambda: client.users().messages().get(userId="me", id=message_id, format="full").execute())
        message = self._parse_message(raw)
        await self._remember(user_id, message, "email")
        return message

    async def search_messages(self, user_id: uuid.UUID, query: str, max_results: int = 20) -> list[GmailMessage]:
        client = await self._client(user_id)
        page = await asyncio.to_thread(lambda: client.users().messages().list(userId="me", q=query, maxResults=max_results).execute())
        return [await self.get_message(user_id, item["id"], client) for item in page.get("messages", [])]

    async def get_unread_messages(self, user_id: uuid.UUID, max_results: int = 20) -> list[GmailMessage]:
        return await self.search_messages(user_id, "is:unread", max_results)

    async def create_draft(self, user_id: uuid.UUID, to: list[str], subject: str, body: str, cc: list[str] | None = None, bcc: list[str] | None = None) -> dict:
        client = await self._client(user_id)
        raw = self._mime(to, subject, body, cc, bcc)
        return await asyncio.to_thread(lambda: client.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute())

    async def send_email(self, user_id: uuid.UUID, to: list[str], subject: str, body: str, cc: list[str] | None = None, bcc: list[str] | None = None) -> GmailMessage:
        client = await self._client(user_id)
        raw = self._mime(to, subject, body, cc, bcc)
        sent = await asyncio.to_thread(lambda: client.users().messages().send(userId="me", body={"raw": raw}).execute())
        message = GmailMessage(id=sent["id"], thread_id=sent.get("threadId", ""), sender="", recipients=", ".join(to), subject=subject, body=body, labels=sent.get("labelIds", ["SENT"]))
        await self._remember(user_id, message, "sent_email")
        return message

    async def test_connection(self, user_id: uuid.UUID) -> str:
        """Verify that the stored OAuth credential can access the Gmail profile."""
        client = await self._client(user_id)
        profile = await asyncio.to_thread(lambda: client.users().getProfile(userId="me").execute())
        return profile["emailAddress"]

    async def _remember(self, user_id: uuid.UUID, message: GmailMessage, role: str) -> None:
        content = f"From: {message.sender}\nTo: {message.recipients}\nSubject: {message.subject}\n\n{message.body}"
        await self.memory.store_external_message(user_id, "gmail", message.id, message.subject or "Gmail message", role, content)
        await self.session.commit()

    @staticmethod
    def _mime(to: list[str], subject: str, body: str, cc: list[str] | None, bcc: list[str] | None) -> str:
        message = EmailMessage()
        message["To"], message["Subject"] = ", ".join(to), subject
        if cc: message["Cc"] = ", ".join(cc)
        if bcc: message["Bcc"] = ", ".join(bcc)
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode()

    @staticmethod
    def _parse_message(raw: dict) -> GmailMessage:
        headers = {header["name"].lower(): header["value"] for header in raw.get("payload", {}).get("headers", [])}
        return GmailMessage(id=raw["id"], thread_id=raw.get("threadId", ""), sender=headers.get("from", ""), recipients=headers.get("to", ""), subject=headers.get("subject", ""), body=GmailService._body(raw.get("payload", {})), labels=raw.get("labelIds", []))

    @staticmethod
    def _body(payload: dict) -> str:
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"] + "===").decode(errors="replace")
        return "\n".join(filter(None, (GmailService._body(part) for part in payload.get("parts", []))))
