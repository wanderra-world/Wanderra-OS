"""Canonical encrypted credential sink for workspace-owned Gmail OAuth grants."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.connection_credentials.contracts import credential_record_type
from app.connection_credentials.models import ConnectionCredential
from app.connection_credentials.repository import ConnectionCredentialRepository
from app.connections.models import Connection
from app.connections.repository import ConnectionRepository
from app.encryption import EnvelopeEncryptionService, KeyProvider, KeyReference
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.oauth_transactions.contracts import OAuthCredentialGrant
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    ProviderCapabilityError,
)
from app.tenancy.models import OutboxEvent


class GmailCredentialBindingError(RuntimeError):
    """Fail-closed connection or credential binding error without secret material."""


class CredentialPayloadLoader(Protocol):
    async def load(self) -> bytes: ...


class CredentialGrantSink(Protocol):
    async def store(
        self,
        *,
        connection_id: uuid.UUID,
        provider_key: str,
        grant: OAuthCredentialGrant,
    ) -> uuid.UUID: ...


class GmailRefreshingCredentialLoader:
    """Refresh expired grants and persist a new encrypted generation before use."""

    def __init__(
        self,
        base: CredentialPayloadLoader,
        sink: CredentialGrantSink,
        *,
        connection_id: uuid.UUID,
        refresher: Callable[[bytes], Awaitable[object]],
        now: Callable[[], datetime] | None = None,
        refresh_skew: timedelta = timedelta(minutes=2),
    ) -> None:
        self._base = base
        self._sink = sink
        self._connection_id = connection_id
        self._refresher = refresher
        self._now = now or (lambda: datetime.now(UTC))
        self._refresh_skew = refresh_skew

    async def load(self) -> bytes:
        payload = await self._base.load()
        try:
            values = json.loads(payload)
            expiry_value = values.get("expiry")
            expiry = (
                datetime.fromisoformat(str(expiry_value).replace("Z", "+00:00"))
                if expiry_value
                else None
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise self._unavailable() from error
        if expiry is None or expiry > self._now() + self._refresh_skew:
            return payload
        try:
            refreshed = await self._refresher(payload)
            grant = OAuthCredentialGrant(
                payload=refreshed.payload,
                scopes=refreshed.scopes,
                provider_account_id=refreshed.provider_account_id,
                credential_kind=refreshed.credential_kind,
                expires_at=refreshed.expires_at,
            )
            await self._sink.store(
                connection_id=self._connection_id,
                provider_key="google_workspace",
                grant=grant,
            )
            return grant.payload
        except Exception as error:
            raise self._unavailable() from error

    @staticmethod
    def _unavailable() -> ProviderCapabilityError:
        return ProviderCapabilityError(
            CanonicalErrorCategory.AUTHENTICATION,
            "The Gmail authorization is unavailable and requires reauthorization.",
        )


class GmailCredentialSink:
    """Persist a Google grant through the accepted H2 encrypted custody boundary."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        key_provider: KeyProvider,
        key_reference: KeyReference,
    ) -> None:
        self._session = session
        self._context = context
        self._key_reference = key_reference
        self._connections = ConnectionRepository(session, context)
        self._credentials = ConnectionCredentialRepository(session, context)
        self._encryption = EnvelopeEncryptionService(session, context, key_provider)
        self._audit = AuditWriterService(session, context)

    async def store(
        self,
        *,
        connection_id: uuid.UUID,
        provider_key: str,
        grant: OAuthCredentialGrant,
    ) -> uuid.UUID:
        connection = await self._connections.get(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=connection_id,
            for_update=True,
        )
        self._validate_binding(connection, provider_key, grant)
        assert connection is not None
        current = await self._credentials.latest_generation(
            connection_id,
            grant.credential_kind,
            for_update=True,
        )
        generation = 1 if current is None else current.generation + 1
        credential_id = uuid.uuid4()
        now = datetime.now(UTC)
        envelope = await self._encryption.encrypt(
            grant.payload,
            connection_id=connection_id,
            record_type=credential_record_type(
                provider_key=provider_key,
                credential_kind=grant.credential_kind,
                generation=generation,
            ),
            record_id=credential_id,
            key_reference=self._key_reference,
            now=now,
        )
        credential = await self._credentials.add_credential(
            ConnectionCredential(
                workspace_id=self._context.tenant.workspace_id,
                id=credential_id,
                connection_id=connection_id,
                provider_key=provider_key,
                credential_kind=grant.credential_kind,
                generation=generation,
                version=1,
                envelope_id=envelope.id,
                status="active",
                scopes=list(grant.scopes),
                expires_at=grant.expires_at,
                verified_at=now,
            )
        )
        if current is not None:
            current.status = "revoked"
            current.revoked_at = now
            current.version += 1
        connection.granted_scopes = sorted(set(grant.scopes))
        connection.status = "active"
        connection.activated_at = connection.activated_at or now
        connection.reauthorization_required_at = None
        connection.last_material_actor_id = self._context.actor.actor_id
        connection.version += 1
        connection.updated_at = now
        await self._record(connection, credential)
        return credential.id

    @staticmethod
    def _validate_binding(
        connection: Connection | None,
        provider_key: str,
        grant: OAuthCredentialGrant,
    ) -> None:
        if connection is None or connection.status in {"revoked", "closed"}:
            raise GmailCredentialBindingError("Gmail connection is unavailable")
        if provider_key != "google_workspace" or connection.provider_key != provider_key:
            raise GmailCredentialBindingError("Gmail provider binding does not match")
        if connection.connection_kind != "workspace_suite":
            raise GmailCredentialBindingError("Gmail connection kind does not match")
        if (
            connection.provider_account_id.strip().lower()
            != grant.provider_account_id.strip().lower()
        ):
            raise GmailCredentialBindingError("Google account binding does not match")

    async def _record(
        self,
        connection: Connection,
        credential: ConnectionCredential,
    ) -> None:
        details = {
            "provider_key": "google_workspace",
            "connection_id": str(connection.id),
            "authorization_generation": credential.generation,
            "scope_count": len(credential.scopes),
        }
        await self._audit.write(
            AuditInput(
                action="gmail.oauth_connected",
                target_type="connection",
                target_id=connection.id,
                outcome="success",
                details=details,
            )
        )
        payload = {
            "connection_id": str(connection.id),
            "provider_key": "google_workspace",
            "authorization_generation": credential.generation,
        }
        self._session.add(
            OutboxEvent(
                workspace_id=self._context.tenant.workspace_id,
                event_type="gmail.oauth.connected",
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="connection",
                aggregate_id=connection.id,
                aggregate_sequence=connection.version,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="restricted",
                payload=payload,
                payload_digest=hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
            )
        )
        await self._session.flush()
