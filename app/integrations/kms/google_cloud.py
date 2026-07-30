"""Google Cloud KMS adapter for the managed KeyProvider port."""

from __future__ import annotations

from app.encryption.contracts import (
    KeyProviderUnavailableError,
    KeyReference,
)


class GoogleCloudKmsKeyProvider:
    """Wrap DEKs with a versioned Google Cloud KMS boundary."""

    def __init__(self, client: object) -> None:
        self._client = client

    @classmethod
    def from_default_credentials(cls) -> GoogleCloudKmsKeyProvider:
        """Create the production adapter using workload identity credentials."""
        from google.cloud.kms_v1 import KeyManagementServiceAsyncClient

        return cls(KeyManagementServiceAsyncClient())

    async def wrap_key(
        self,
        plaintext_key: bytes,
        key_reference: KeyReference,
        *,
        authenticated_data: bytes,
    ) -> bytes:
        try:
            response = await self._client.encrypt(
                request={
                    "name": self._version_name(key_reference),
                    "plaintext": plaintext_key,
                    "additional_authenticated_data": authenticated_data,
                }
            )
            return bytes(response.ciphertext)
        except Exception as error:
            raise KeyProviderUnavailableError(
                "managed key wrap failed"
            ) from error

    async def unwrap_key(
        self,
        wrapped_key: bytes,
        key_reference: KeyReference,
        *,
        authenticated_data: bytes,
    ) -> bytes:
        try:
            response = await self._client.decrypt(
                request={
                    "name": key_reference.resource,
                    "ciphertext": wrapped_key,
                    "additional_authenticated_data": authenticated_data,
                }
            )
            return bytes(response.plaintext)
        except Exception as error:
            raise KeyProviderUnavailableError(
                "managed key unwrap failed"
            ) from error

    @staticmethod
    def _version_name(key_reference: KeyReference) -> str:
        return f"{key_reference.resource}/cryptoKeyVersions/{key_reference.version}"
