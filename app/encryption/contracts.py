"""Versioned envelope-encryption contracts and KMS port."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

ENVELOPE_FORMAT_VERSION = 1
ENVELOPE_ALGORITHM = "AES-256-GCM"


class EncryptionError(RuntimeError):
    """Fail-closed error without plaintext or key material."""


class KeyProviderUnavailableError(EncryptionError):
    """The managed key provider cannot safely complete the operation."""


@dataclass(frozen=True, slots=True)
class KeyReference:
    """Stable managed KEK resource and immutable provider version."""

    resource: str
    version: str

    def __post_init__(self) -> None:
        if not self.resource.strip() or not self.version.strip():
            raise ValueError("key resource and version are required")


@dataclass(frozen=True, slots=True)
class EncryptionContext:
    """Security coordinates authenticated with every encrypted record."""

    workspace_id: uuid.UUID
    connection_id: uuid.UUID
    record_type: str
    record_id: uuid.UUID
    format_version: int = ENVELOPE_FORMAT_VERSION

    def __post_init__(self) -> None:
        if not self.record_type.strip():
            raise ValueError("record type is required")
        if self.format_version != ENVELOPE_FORMAT_VERSION:
            raise ValueError("unsupported envelope format")

    def authenticated_data(self) -> bytes:
        return (
            f"{self.workspace_id}|{self.connection_id}|{self.record_type}|"
            f"{self.record_id}|{self.format_version}"
        ).encode()


@dataclass(frozen=True, slots=True)
class EncryptedEnvelopeData:
    """Ciphertext plus wrapped DEK; never contains plaintext or a raw DEK."""

    context: EncryptionContext
    algorithm: str
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    key_reference: KeyReference
    checksum: str
    encrypted_at: datetime


class KeyProvider(Protocol):
    """Narrow managed-KMS boundary available to runtime and rotation services."""

    async def wrap_key(
        self,
        plaintext_key: bytes,
        key_reference: KeyReference,
        *,
        authenticated_data: bytes,
    ) -> bytes: ...

    async def unwrap_key(
        self,
        wrapped_key: bytes,
        key_reference: KeyReference,
        *,
        authenticated_data: bytes,
    ) -> bytes: ...
