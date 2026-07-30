"""Provider-neutral contracts for H2-03 OAuth transactions."""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_STATE = re.compile(
    r"^v1\.([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})\.([A-Za-z0-9_-]{40,})$"
)


class OAuthError(RuntimeError):
    """Fail-closed OAuth error without protocol secret material."""


class OAuthAuthorizationError(OAuthError):
    """The actor may not create or administer an OAuth transaction."""


class OAuthBindingError(OAuthError):
    """Callback security coordinates do not match the transaction."""


class OAuthReplayError(OAuthError):
    """A one-time state was replayed or is no longer pending."""


class OAuthScopeError(OAuthError):
    """Returned authorization scopes fail the approved policy."""


class OAuthPurpose(StrEnum):
    CONNECT = "connect"
    REAUTHORIZE = "reauthorize"


class OAuthStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


def _identifier(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{field} must be a stable lowercase identifier")
    return normalized


def normalize_values(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted({value.strip() for value in values if value.strip()}))
    if any(len(value) > 512 for value in normalized):
        raise ValueError("OAuth metadata value is too long")
    return normalized


def issue_state_token(workspace_id: uuid.UUID) -> str:
    """Create an opaque state with a non-secret RLS routing hint."""
    return f"v1.{workspace_id}.{secrets.token_urlsafe(32)}"


def parse_workspace_hint(raw_state: str) -> uuid.UUID:
    match = _STATE.fullmatch(raw_state)
    if match is None:
        raise OAuthBindingError("OAuth state format is invalid")
    return uuid.UUID(match.group(1))


def state_digest(raw_state: str) -> str:
    parse_workspace_hint(raw_state)
    return hashlib.sha256(raw_state.encode()).hexdigest()


def validate_returned_scopes(
    *,
    returned_scopes: tuple[str, ...],
    required_scopes: tuple[str, ...],
    allowed_scopes: tuple[str, ...],
) -> tuple[str, ...]:
    returned = set(normalize_values(returned_scopes))
    required = set(normalize_values(required_scopes))
    allowed = set(normalize_values(allowed_scopes))
    if not required.issubset(returned):
        raise OAuthScopeError("OAuth grant is missing required scope")
    if not returned.issubset(allowed):
        raise OAuthScopeError("OAuth grant contains unexpected scope")
    return tuple(sorted(returned))


@dataclass(frozen=True, slots=True)
class OAuthSecurityPolicy:
    allowed_redirect_uris: frozenset[str]
    allowed_issuers: frozenset[str]
    allowed_scopes: frozenset[str]
    lifetime: timedelta = timedelta(minutes=10)

    def __post_init__(self) -> None:
        if not self.allowed_redirect_uris or not self.allowed_issuers:
            raise ValueError("OAuth redirect and issuer allowlists are required")
        if self.lifetime <= timedelta(0) or self.lifetime > timedelta(minutes=30):
            raise ValueError("OAuth transaction lifetime is invalid")


@dataclass(frozen=True, slots=True)
class OAuthTransactionCreate:
    transaction_id: uuid.UUID
    connection_id: uuid.UUID
    provider_key: str
    purpose: OAuthPurpose
    redirect_uri: str
    issuer: str
    requested_capabilities: tuple[str, ...]
    requested_scopes: tuple[str, ...]
    required_scopes: tuple[str, ...]
    incremental: bool = True

    def validated(self, policy: OAuthSecurityPolicy) -> OAuthTransactionCreate:
        provider_key = _identifier(self.provider_key, field="provider key")
        capabilities = normalize_values(self.requested_capabilities)
        requested = normalize_values(self.requested_scopes)
        required = normalize_values(self.required_scopes)
        if self.redirect_uri not in policy.allowed_redirect_uris:
            raise ValueError("OAuth redirect URI is not allowed")
        if self.issuer not in policy.allowed_issuers:
            raise ValueError("OAuth issuer is not allowed")
        if not requested or not required or not set(required).issubset(requested):
            raise ValueError("OAuth requested and required scopes are invalid")
        if not set(requested).issubset(policy.allowed_scopes):
            raise ValueError("OAuth requested scope is not allowed")
        if not capabilities:
            raise ValueError("OAuth requested capability is required")
        return replace(
            self,
            provider_key=provider_key,
            requested_capabilities=capabilities,
            requested_scopes=requested,
            required_scopes=required,
        )


@dataclass(frozen=True, slots=True, repr=False)
class OAuthCallback:
    state: str
    code: str | None
    returned_scopes: tuple[str, ...]
    issuer: str
    redirect_uri: str
    received_at: datetime
    error_code: str | None = None
    error_description: str | None = None

    def __repr__(self) -> str:
        return (
            "OAuthCallback(state=<redacted>, code=<redacted>, "
            f"returned_scopes={len(self.returned_scopes)}, "
            f"issuer={self.issuer!r}, redirect_uri={self.redirect_uri!r}, "
            f"error_code={self.error_code!r}, error_description=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class OAuthCredentialGrant:
    """Ephemeral result from a protocol adapter to an H2-02 custody sink."""

    payload: bytes
    scopes: tuple[str, ...]
    provider_account_id: str
    credential_kind: str
    expires_at: datetime | None = None

    def __repr__(self) -> str:
        return (
            "OAuthCredentialGrant(payload=<redacted>, "
            f"scopes={len(self.scopes)}, "
            f"provider_account_id={self.provider_account_id!r}, "
            f"credential_kind={self.credential_kind!r})"
        )


class OAuthProtocolDispatcher(Protocol):
    async def exchange(
        self,
        *,
        provider_key: str,
        authorization_code: str,
        pkce_verifier: bytes,
        redirect_uri: str,
    ) -> OAuthCredentialGrant: ...


class CredentialGenerationSink(Protocol):
    async def store(
        self,
        *,
        connection_id: uuid.UUID,
        provider_key: str,
        grant: OAuthCredentialGrant,
    ) -> uuid.UUID: ...


_TRANSITIONS = {
    OAuthStatus.PENDING: frozenset(
        {
            OAuthStatus.COMPLETED,
            OAuthStatus.CANCELLED,
            OAuthStatus.FAILED,
            OAuthStatus.EXPIRED,
        }
    )
}


def require_transition(current: OAuthStatus, target: OAuthStatus) -> None:
    if target not in _TRANSITIONS.get(current, frozenset()):
        raise ValueError("OAuth transaction transition is invalid")
