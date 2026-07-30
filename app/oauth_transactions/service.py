"""Transactional, provider-neutral H2-03 OAuth lifecycle service."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.repository import ConnectionRepository
from app.connections.service import H1ConnectionAuthorizer
from app.encryption import EnvelopeEncryptionService, KeyProvider, KeyReference
from app.encryption.models import EncryptedEnvelope
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.oauth_transactions.contracts import (
    CredentialGenerationSink,
    OAuthAuthorizationError,
    OAuthBindingError,
    OAuthCallback,
    OAuthProtocolDispatcher,
    OAuthReplayError,
    OAuthScopeError,
    OAuthSecurityPolicy,
    OAuthStatus,
    OAuthTransactionCreate,
    issue_state_token,
    parse_workspace_hint,
    state_digest,
    validate_returned_scopes,
)
from app.oauth_transactions.models import OAuthTransaction
from app.oauth_transactions.repository import OAuthTransactionRepository
from app.tenancy.models import OutboxEvent


class OAuthAuthorizer(Protocol):
    async def authorize(
        self, context: ExecutionContext, permission_key: str
    ) -> bool: ...


@dataclass(frozen=True, slots=True, repr=False)
class OAuthStartResult:
    transaction: OAuthTransaction
    state: str

    def __repr__(self) -> str:
        return f"OAuthStartResult(transaction_id={self.transaction.id}, state=<redacted>)"


class OAuthTransactionService:
    """Create and consume one-time OAuth transactions in a caller transaction."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        policy: OAuthSecurityPolicy,
        key_provider: KeyProvider,
        dispatcher: OAuthProtocolDispatcher,
        credential_sink: CredentialGenerationSink,
        authorizer: OAuthAuthorizer | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._policy = policy
        self._dispatcher = dispatcher
        self._sink = credential_sink
        self._authorizer = authorizer or H1ConnectionAuthorizer(session)
        self._repository = OAuthTransactionRepository(session, context)
        self._connections = ConnectionRepository(session, context)
        self._encryption = EnvelopeEncryptionService(session, context, key_provider)
        self._audit = AuditWriterService(session, context)

    async def start(
        self,
        command: OAuthTransactionCreate,
        *,
        pkce_verifier: bytes,
        key_reference: KeyReference,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> OAuthStartResult:
        await self._require_authorized()
        command = command.validated(self._policy)
        if not pkce_verifier or len(pkce_verifier) > 512:
            raise OAuthBindingError("PKCE verifier is invalid")
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise OAuthBindingError("OAuth idempotency key is invalid")
        connection = await self._connections.get(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=command.connection_id,
        )
        if (
            connection is None
            or connection.provider_key != command.provider_key
            or connection.status in {"revoked", "closed"}
        ):
            raise OAuthBindingError("OAuth connection binding is invalid")
        digest = self._request_digest(command)
        await self._repository.lock_idempotency(idempotency_key)
        existing = await self._repository.by_idempotency(idempotency_key)
        if existing is not None:
            if existing.request_digest != digest or existing.status != "pending":
                raise OAuthReplayError("OAuth start replay is invalid")
            return OAuthStartResult(existing, await self._raw_state(existing))

        issued_at = now or datetime.now(UTC)
        raw_state = issue_state_token(self._context.tenant.workspace_id)
        secret = json.dumps(
            {
                "state": raw_state,
                "pkce": pkce_verifier.decode("utf-8"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        envelope = await self._encryption.encrypt(
            secret,
            connection_id=command.connection_id,
            record_type=(
                f"oauth_transaction_secret:{command.provider_key}:"
                f"{command.purpose.value}"
            ),
            record_id=command.transaction_id,
            key_reference=key_reference,
            now=issued_at,
        )
        transaction = await self._repository.add(
            OAuthTransaction(
                workspace_id=self._context.tenant.workspace_id,
                id=command.transaction_id,
                connection_id=command.connection_id,
                provider_key=command.provider_key,
                actor_id=self._context.actor.actor_id,
                session_id=self._context.actor.session_id,
                membership_id=self._context.actor.membership_id,
                authorization_decision_id=(
                    self._context.actor.authorization_decision_id
                ),
                secret_envelope_id=envelope.id,
                purpose=command.purpose.value,
                state_digest=state_digest(raw_state),
                request_digest=digest,
                idempotency_key=idempotency_key,
                redirect_uri=command.redirect_uri,
                issuer=command.issuer,
                requested_capabilities=list(command.requested_capabilities),
                requested_scopes=list(command.requested_scopes),
                required_scopes=list(command.required_scopes),
                returned_scopes=[],
                incremental=command.incremental,
                status=OAuthStatus.PENDING.value,
                correlation_id=self._context.request.correlation_id,
                version=1,
                expires_at=issued_at + self._policy.lifetime,
                created_at=issued_at,
                updated_at=issued_at,
            )
        )
        await self._record(transaction, "oauth.transaction_started")
        return OAuthStartResult(transaction, raw_state)

    async def complete(self, callback: OAuthCallback) -> OAuthTransaction:
        if parse_workspace_hint(callback.state) != self._context.tenant.workspace_id:
            raise OAuthBindingError("OAuth workspace binding does not match")
        transaction = await self._repository.by_state(
            state_digest(callback.state), for_update=True
        )
        if transaction is None:
            raise OAuthBindingError("OAuth transaction is unavailable")
        if transaction.status != OAuthStatus.PENDING.value:
            raise OAuthReplayError("OAuth transaction is no longer pending")
        await self._require_authorized()
        self._require_actor_binding(transaction)
        if callback.received_at > transaction.expires_at:
            await self._fail(transaction, OAuthStatus.EXPIRED, "expired", callback.received_at)
            raise OAuthReplayError("OAuth transaction expired")
        if (
            callback.redirect_uri != transaction.redirect_uri
            or callback.issuer != transaction.issuer
        ):
            await self._fail(
                transaction, OAuthStatus.FAILED, "binding_mismatch", callback.received_at
            )
            raise OAuthBindingError("OAuth callback binding does not match")
        if callback.error_code is not None:
            reason = (
                "provider_denied"
                if callback.error_code == "access_denied"
                else "provider_error"
            )
            await self._fail(
                transaction, OAuthStatus.FAILED, reason, callback.received_at
            )
            raise OAuthBindingError(f"OAuth {reason.replace('_', ' ')}")
        if not callback.code:
            await self._fail(
                transaction,
                OAuthStatus.FAILED,
                "authorization_code_missing",
                callback.received_at,
            )
            raise OAuthBindingError("OAuth authorization code is missing")
        try:
            returned = validate_returned_scopes(
                returned_scopes=callback.returned_scopes,
                required_scopes=tuple(transaction.required_scopes),
                allowed_scopes=tuple(self._policy.allowed_scopes),
            )
        except OAuthScopeError:
            await self._fail(
                transaction, OAuthStatus.FAILED, "scope_policy_denied", callback.received_at
            )
            raise
        values = await self._secret_values(transaction)
        if not hmac.compare_digest(values["state"], callback.state):
            raise OAuthBindingError("OAuth state binding does not match")
        grant = await self._dispatcher.exchange(
            provider_key=transaction.provider_key,
            authorization_code=callback.code,
            pkce_verifier=values["pkce"].encode(),
            redirect_uri=transaction.redirect_uri,
        )
        validate_returned_scopes(
            returned_scopes=grant.scopes,
            required_scopes=tuple(transaction.required_scopes),
            allowed_scopes=tuple(self._policy.allowed_scopes),
        )
        transaction.credential_id = await self._sink.store(
            connection_id=transaction.connection_id,
            provider_key=transaction.provider_key,
            grant=grant,
        )
        transaction.returned_scopes = list(returned)
        transaction.status = OAuthStatus.COMPLETED.value
        transaction.completed_at = callback.received_at
        transaction.version += 1
        transaction.updated_at = callback.received_at
        await self._record(transaction, "oauth.transaction_completed")
        return transaction

    async def cancel(
        self,
        transaction_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> OAuthTransaction:
        await self._require_authorized()
        transaction = await self._repository.by_id(
            transaction_id, for_update=True
        )
        if transaction is None or transaction.status != OAuthStatus.PENDING.value:
            raise OAuthReplayError("OAuth transaction is no longer pending")
        self._require_actor_binding(transaction)
        changed_at = now or datetime.now(UTC)
        transaction.status = OAuthStatus.CANCELLED.value
        transaction.cancelled_at = changed_at
        transaction.version += 1
        transaction.updated_at = changed_at
        await self._record(transaction, "oauth.transaction_cancelled")
        return transaction

    async def _raw_state(self, transaction: OAuthTransaction) -> str:
        return (await self._secret_values(transaction))["state"]

    async def _secret_values(self, transaction: OAuthTransaction) -> dict[str, str]:
        envelope = await self._session.get(
            EncryptedEnvelope,
            (transaction.workspace_id, transaction.secret_envelope_id),
        )
        if envelope is None:
            raise OAuthBindingError("OAuth transaction secret is unavailable")
        return json.loads((await self._encryption.decrypt(envelope)).decode())

    async def _fail(
        self,
        transaction: OAuthTransaction,
        status: OAuthStatus,
        reason: str,
        changed_at: datetime,
    ) -> None:
        transaction.status = status.value
        transaction.failure_code = reason
        transaction.failed_at = changed_at
        transaction.version += 1
        transaction.updated_at = changed_at
        await self._record(transaction, f"oauth.transaction_{status.value}")

    def _require_actor_binding(self, transaction: OAuthTransaction) -> None:
        actor = self._context.actor
        if (
            transaction.actor_id != actor.actor_id
            or transaction.session_id != actor.session_id
            or transaction.membership_id != actor.membership_id
            or transaction.authorization_decision_id
            != actor.authorization_decision_id
        ):
            raise OAuthBindingError("OAuth actor binding does not match")

    async def _require_authorized(self) -> None:
        if not await self._authorizer.authorize(
            self._context, "manage_workspace"
        ):
            raise OAuthAuthorizationError("OAuth administration is denied")

    @staticmethod
    def _request_digest(command: OAuthTransactionCreate) -> str:
        payload = {
            "connection_id": str(command.connection_id),
            "provider_key": command.provider_key,
            "purpose": command.purpose.value,
            "redirect_uri": command.redirect_uri,
            "issuer": command.issuer,
            "requested_capabilities": command.requested_capabilities,
            "requested_scopes": command.requested_scopes,
            "required_scopes": command.required_scopes,
            "incremental": command.incremental,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _record(self, transaction: OAuthTransaction, action: str) -> None:
        details = {
            "transaction_id": str(transaction.id),
            "provider_key": transaction.provider_key,
            "purpose": transaction.purpose,
            "status": transaction.status,
            "version": transaction.version,
        }
        audit = await self._audit.write(
            AuditInput(
                action=action,
                target_type="oauth_transaction",
                target_id=transaction.id,
                outcome="success",
                details=details,
                classification="restricted",
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=transaction.workspace_id,
                id=uuid.uuid4(),
                event_type=action,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="oauth_transaction",
                aggregate_id=transaction.id,
                aggregate_sequence=transaction.version,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="restricted",
                payload={"audit_event_id": str(audit.id), **details},
            )
        )
        await self._session.flush()
