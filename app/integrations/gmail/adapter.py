"""Google mail adapter confined to the integration SDK boundary."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from email.message import EmailMessage as MimeMessage
from email.utils import getaddresses, parseaddr
from typing import Protocol

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.capability_routing.credentials import ManagedConnectionCredentialLoader
from app.email_capability.contracts import EmailResourceObserver
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    ExtensionEnvelope,
    MutationContext,
    OpaqueCursor,
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


class GmailApi(Protocol):
    """Narrow SDK façade; raw provider values cannot cross the adapter."""

    async def profile(self) -> dict[str, object]: ...

    async def message_page(
        self, *, query: str | None, limit: int, cursor: str | None
    ) -> dict[str, object]: ...

    async def message(self, external_id: str) -> dict[str, object]: ...
    async def create_draft(self, raw_message: str) -> dict[str, object]: ...
    async def send(self, raw_message: str) -> dict[str, object]: ...


class GoogleGmailApi:
    """Async façade around the supported provider SDK resource."""

    def __init__(self, resource: object) -> None:
        self._resource = resource

    def _users(self):
        return self._resource.users()  # type: ignore[attr-defined,no-any-return]

    async def profile(self) -> dict[str, object]:
        return await asyncio.to_thread(
            lambda: self._users().getProfile(userId="me").execute()
        )

    async def message_page(
        self, *, query: str | None, limit: int, cursor: str | None
    ) -> dict[str, object]:
        arguments: dict[str, object] = {"userId": "me", "maxResults": limit}
        if query is not None:
            arguments["q"] = query
        if cursor is not None:
            arguments["pageToken"] = cursor
        return await asyncio.to_thread(
            lambda: self._users().messages().list(**arguments).execute()
        )

    async def message(self, external_id: str) -> dict[str, object]:
        return await asyncio.to_thread(
            lambda: self._users()
            .messages()
            .get(userId="me", id=external_id, format="full")
            .execute()
        )

    async def create_draft(self, raw_message: str) -> dict[str, object]:
        return await asyncio.to_thread(
            lambda: self._users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw_message}})
            .execute()
        )

    async def send(self, raw_message: str) -> dict[str, object]:
        sent = await asyncio.to_thread(
            lambda: self._users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )
        return await self.message(str(sent["id"]))


async def build_google_gmail_api(serialized_credential: bytes) -> GmailApi:
    """Build a provider SDK client from decrypted managed credential material."""
    values = json.loads(serialized_credential)
    credentials = Credentials.from_authorized_user_info(values)
    resource = await asyncio.to_thread(
        build,
        "gmail",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )
    return GoogleGmailApi(resource)


class GmailCredentialLoader(Protocol):
    async def load(self) -> bytes: ...


class GmailApiBuilder(Protocol):
    async def __call__(self, serialized_credential: bytes) -> GmailApi: ...


class GmailManagedPortFactory:
    """Loads a managed credential only when the authorized factory is opened."""

    def __init__(
        self,
        credentials: GmailCredentialLoader,
        builder: GmailApiBuilder,
        observer: EmailResourceObserver | None = None,
    ) -> None:
        self._credentials = credentials
        self._builder = builder
        self._observer = observer

    async def canonical_port(self) -> GmailEmailAdapter:
        serialized = await self._credentials.load()
        return GmailEmailAdapter(
            await self._builder(serialized), self._observer
        )


ManagedGmailCredentialLoader = ManagedConnectionCredentialLoader


class GmailEmailAdapter:
    def __init__(
        self, api: GmailApi, observer: EmailResourceObserver | None = None
    ) -> None:
        self._api = api
        self._observer = observer

    async def profile(self) -> EmailProfile:
        try:
            raw = await self._api.profile()
            return EmailProfile(email_address=str(raw["emailAddress"]))
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe_error(error) from error

    async def list_messages(self, request: EmailListRequest) -> Page[EmailMessage]:
        return await self._page(request.page.limit, request.page.cursor, None)

    async def list_unread(self, request: EmailListRequest) -> Page[EmailMessage]:
        return await self._page(request.page.limit, request.page.cursor, "is:unread")

    async def search_messages(
        self, request: EmailSearchRequest
    ) -> Page[EmailMessage]:
        return await self._page(
            request.page.limit, request.page.cursor, request.query
        )

    async def create_draft(
        self, message: EmailMessageCreate, context: MutationContext
    ) -> EmailMessage:
        del context
        try:
            raw = await self._api.create_draft(self._mime(message))
            value = raw.get("message", raw)
            assert isinstance(value, dict)
            return await self._observed(value)
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe_error(error) from error

    async def send_message(
        self, message: EmailMessageCreate, context: MutationContext
    ) -> EmailMessage:
        del context
        try:
            return await self._observed(
                await self._api.send(self._mime(message))
            )
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe_error(error) from error

    async def _page(
        self, limit: int, cursor: OpaqueCursor | None, query: str | None
    ) -> Page[EmailMessage]:
        try:
            raw = await self._api.message_page(
                query=query, limit=limit, cursor=cursor.value if cursor else None
            )
            references = raw.get("messages", [])
            assert isinstance(references, list)
            items: list[EmailMessage] = []
            for reference in references:
                if isinstance(reference, dict) and "id" in reference:
                    items.append(
                        await self._observed(
                            await self._api.message(str(reference["id"]))
                        )
                    )
            token = raw.get("nextPageToken")
            return Page(
                tuple(items),
                OpaqueCursor(str(token)) if isinstance(token, str) and token else None,
            )
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe_error(error) from error

    async def _observed(self, raw: dict[str, object]) -> EmailMessage:
        message = self._message(raw)
        if self._observer is not None:
            await self._observer.observe(message)
        return message

    @classmethod
    def _message(cls, raw: dict[str, object]) -> EmailMessage:
        payload = raw.get("payload", {})
        assert isinstance(payload, dict)
        raw_headers = payload.get("headers", [])
        headers = {
            str(item.get("name", "")).lower(): str(item.get("value", ""))
            for item in raw_headers
            if isinstance(item, dict)
        }
        sender_name, sender_address = parseaddr(headers.get("from", ""))
        recipients = tuple(
            EmailAddress(address, name or None)
            for name, address in getaddresses(
                [headers.get("to", ""), headers.get("cc", "")]
            )
            if address
        )
        milliseconds = raw.get("internalDate")
        received_at = (
            datetime.fromtimestamp(int(str(milliseconds)) / 1000, tz=UTC)
            if milliseconds is not None
            else None
        )
        history_id = raw.get("historyId")
        extensions = ExtensionEnvelope(
            {"google.gmail/history_id": str(history_id)}
            if history_id is not None
            else {}
        )
        labels = raw.get("labelIds", [])
        return EmailMessage(
            external_id=str(raw["id"]),
            thread_external_id=(
                str(raw["threadId"]) if raw.get("threadId") is not None else None
            ),
            sender=EmailAddress(sender_address or "unknown@invalid.local", sender_name or None),
            recipients=recipients,
            subject=headers.get("subject", ""),
            body_text=cls._body(payload),
            labels=tuple(str(label) for label in labels)
            if isinstance(labels, list)
            else (),
            received_at=received_at,
            version=str(history_id) if history_id is not None else None,
            extensions=extensions,
        )

    @classmethod
    def _body(cls, payload: dict[str, object]) -> str:
        body = payload.get("body", {})
        if payload.get("mimeType") == "text/plain" and isinstance(body, dict):
            encoded = body.get("data")
            if isinstance(encoded, str) and encoded:
                return base64.urlsafe_b64decode(encoded + "===").decode(
                    errors="replace"
                )
        parts = payload.get("parts", [])
        if not isinstance(parts, list):
            return ""
        return "\n".join(
            filter(None, (cls._body(part) for part in parts if isinstance(part, dict)))
        )

    @staticmethod
    def _mime(message: EmailMessageCreate) -> str:
        value = MimeMessage()
        value["To"] = ", ".join(message.to)
        value["Subject"] = message.subject
        if message.cc:
            value["Cc"] = ", ".join(message.cc)
        if message.bcc:
            value["Bcc"] = ", ".join(message.bcc)
        value.set_content(message.body_text)
        return base64.urlsafe_b64encode(value.as_bytes()).decode()

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
            429: CanonicalErrorCategory.RATE_LIMIT,
        }.get(status, CanonicalErrorCategory.TRANSIENT)
        return ProviderCapabilityError(category, "Email provider operation failed.")
