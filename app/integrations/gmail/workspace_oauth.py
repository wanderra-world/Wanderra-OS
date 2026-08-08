"""IP-02 workspace-owned Gmail OAuth application composition."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.encryption.contracts import KeyReference
from app.integrations.gmail.oauth import GmailOAuthProtocol, GmailOAuthScopeProfile
from app.oauth_transactions.contracts import (
    OAuthCallback,
    OAuthPurpose,
    OAuthTransactionCreate,
)
from app.oauth_transactions.models import OAuthTransaction
from app.oauth_transactions.service import OAuthStartResult


class CanonicalOAuthTransactions(Protocol):
    async def start(
        self,
        command: OAuthTransactionCreate,
        *,
        pkce_verifier: bytes,
        key_reference: KeyReference,
        idempotency_key: str,
    ) -> OAuthStartResult: ...

    async def complete(self, callback: OAuthCallback) -> OAuthTransaction: ...


@dataclass(frozen=True, slots=True)
class GmailAuthorizationStart:
    connection_id: uuid.UUID
    operations: tuple[str, ...]
    idempotency_key: str
    purpose: OAuthPurpose = OAuthPurpose.CONNECT

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip() or len(self.idempotency_key) > 128:
            raise ValueError("Gmail OAuth idempotency key is invalid")


@dataclass(frozen=True, slots=True, repr=False)
class GmailAuthorizationResult:
    transaction_id: uuid.UUID
    authorization_url: str

    def __repr__(self) -> str:
        return (
            "GmailAuthorizationResult("
            f"transaction_id={self.transaction_id}, authorization_url=<redacted>)"
        )


class GmailWorkspaceOAuthService:
    """Compose Gmail with H2 OAuth; connection ownership remains canonical."""

    def __init__(
        self,
        *,
        transactions: CanonicalOAuthTransactions,
        protocol: GmailOAuthProtocol,
        redirect_uri: str,
        issuer: str,
    ) -> None:
        self._transactions = transactions
        self._protocol = protocol
        self._redirect_uri = redirect_uri
        self._issuer = issuer

    async def start(
        self,
        request: GmailAuthorizationStart,
        *,
        key_reference: KeyReference,
    ) -> GmailAuthorizationResult:
        profile = GmailOAuthScopeProfile.for_operations(request.operations)
        verifier = secrets.token_urlsafe(64).encode()
        transaction_id = uuid.uuid4()
        started = await self._transactions.start(
            OAuthTransactionCreate(
                transaction_id=transaction_id,
                connection_id=request.connection_id,
                provider_key="google_workspace",
                purpose=request.purpose,
                redirect_uri=self._redirect_uri,
                issuer=self._issuer,
                requested_capabilities=("email",),
                requested_scopes=profile.scopes,
                required_scopes=profile.scopes,
                incremental=True,
            ),
            pkce_verifier=verifier,
            key_reference=key_reference,
            idempotency_key=request.idempotency_key,
        )
        return GmailAuthorizationResult(
            transaction_id=started.transaction.id,
            authorization_url=self._protocol.authorization_url(
                state=started.state,
                pkce_verifier=verifier,
                scopes=profile.scopes,
            ),
        )

    async def complete(self, callback: OAuthCallback) -> uuid.UUID:
        """Consume a callback through the canonical single-use transaction service."""
        completed = await self._transactions.complete(callback)
        return completed.connection_id
