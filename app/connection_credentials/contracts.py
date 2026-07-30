"""Provider-neutral contracts for H2-02 connection credential custody."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")


class CredentialError(RuntimeError):
    """Fail-closed credential error that never includes secret material."""


class CredentialAuthorizationError(CredentialError):
    """The actor may not administer connection credentials."""


class CredentialStateError(CredentialError):
    """The requested credential lifecycle transition is invalid."""


class CredentialMigrationError(CredentialError):
    """Shadow migration could not be proven safe."""


class CredentialStatus(StrEnum):
    SHADOW_VERIFIED = "shadow_verified"
    ACTIVE = "active"
    REAUTHORIZATION_REQUIRED = "reauthorization_required"
    REVOKED = "revoked"
    DISABLED = "disabled"


class InventoryStatus(StrEnum):
    ELIGIBLE = "eligible"
    MIGRATED = "migrated"
    VERIFIED = "verified"
    REAUTHORIZATION_REQUIRED = "reauthorization_required"
    FAILED = "failed"


def normalized_identifier(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{field} must be a stable lowercase identifier")
    return normalized


def normalize_scopes(scopes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({scope.strip() for scope in scopes if scope.strip()}))
    if any(len(scope) > 512 for scope in normalized):
        raise ValueError("credential scope is too long")
    return normalized


def canonical_credential_payload(payload: bytes) -> bytes:
    """Canonicalize JSON credentials for semantic shadow comparison."""
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CredentialMigrationError("legacy credential payload is invalid") from error
    if not isinstance(value, dict):
        raise CredentialMigrationError("legacy credential payload is invalid")
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def credential_record_type(
    *,
    provider_key: str,
    credential_kind: str,
    generation: int,
) -> str:
    if generation < 1:
        raise ValueError("credential generation must be positive")
    provider = normalized_identifier(provider_key, field="provider key")
    kind = normalized_identifier(credential_kind, field="credential kind")
    return f"connection_credential:{provider}:{kind}:g{generation}"


@dataclass(frozen=True, slots=True)
class PhaseOneCredentialSnapshot:
    """Ephemeral legacy input; plaintext is never represented in persistence."""

    source_system: str
    source_record_id: str
    legacy_ciphertext: bytes
    plaintext: bytes
    scopes: tuple[str, ...]
    updated_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        normalized_identifier(self.source_system, field="source system")
        if not self.source_record_id.strip():
            raise ValueError("source record id is required")
        if not self.legacy_ciphertext or not self.plaintext:
            raise ValueError("legacy ciphertext and plaintext are required")
        normalize_scopes(self.scopes)

    @property
    def source_checksum(self) -> str:
        return hashlib.sha256(self.legacy_ciphertext).hexdigest()

    def __repr__(self) -> str:
        return (
            "PhaseOneCredentialSnapshot("
            f"source_system={self.source_system!r}, "
            f"source_record_id={self.source_record_id!r}, "
            "legacy_ciphertext=<redacted>, plaintext=<redacted>, "
            f"scopes={len(self.scopes)})"
        )


@dataclass(frozen=True, slots=True)
class ShadowMigrationCommand:
    connection_id: uuid.UUID
    provider_key: str
    credential_kind: str
    snapshot: PhaseOneCredentialSnapshot
    required_scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_identifier(self.provider_key, field="provider key")
        normalized_identifier(self.credential_kind, field="credential kind")
        normalize_scopes(self.required_scopes)


@dataclass(frozen=True, slots=True)
class InventorySummary:
    row_count: int
    eligible_count: int
    verified_count: int
    exception_count: int
    inventory_checksum: str
    scope_inventory: tuple[str, ...]
