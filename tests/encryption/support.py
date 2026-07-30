"""Test-only managed KMS implementation with no plaintext fixtures."""

from __future__ import annotations

import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.encryption.contracts import (
    KeyProviderUnavailableError,
    KeyReference,
)


class MockManagedKeyProvider:
    def __init__(self, keys: dict[KeyReference, bytes]) -> None:
        self.keys = keys
        self.disabled: set[KeyReference] = set()
        self.available = True

    async def wrap_key(
        self,
        plaintext_key: bytes,
        key_reference: KeyReference,
        *,
        authenticated_data: bytes,
    ) -> bytes:
        key = self._key(key_reference)
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(key).encrypt(
            nonce,
            plaintext_key,
            self._aad(key_reference, authenticated_data),
        )

    async def unwrap_key(
        self,
        wrapped_key: bytes,
        key_reference: KeyReference,
        *,
        authenticated_data: bytes,
    ) -> bytes:
        key = self._key(key_reference)
        try:
            return AESGCM(key).decrypt(
                wrapped_key[:12],
                wrapped_key[12:],
                self._aad(key_reference, authenticated_data),
            )
        except InvalidTag as error:
            raise KeyProviderUnavailableError(
                "managed key authentication failed"
            ) from error

    def _key(self, reference: KeyReference) -> bytes:
        if not self.available or reference in self.disabled:
            raise KeyProviderUnavailableError("managed key unavailable")
        try:
            return self.keys[reference]
        except KeyError as error:
            raise KeyProviderUnavailableError("managed key unavailable") from error

    @staticmethod
    def _aad(reference: KeyReference, authenticated_data: bytes) -> bytes:
        return (
            f"{reference.resource}|{reference.version}|".encode()
            + authenticated_data
        )
