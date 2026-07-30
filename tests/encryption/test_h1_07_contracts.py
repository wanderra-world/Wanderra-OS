"""Unit tests for H1-07 encryption contracts and managed KMS adapter."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.encryption.contracts import (
    ENVELOPE_FORMAT_VERSION,
    EncryptionContext,
    KeyProviderUnavailableError,
    KeyReference,
)
from app.integrations.kms.google_cloud import GoogleCloudKmsKeyProvider


def test_encryption_context_is_versioned_immutable_and_tenant_bound() -> None:
    context = EncryptionContext(
        workspace_id=uuid4(),
        connection_id=uuid4(),
        record_type="google_oauth_credential",
        record_id=uuid4(),
    )
    assert context.format_version == ENVELOPE_FORMAT_VERSION
    assert str(context.workspace_id).encode() in context.authenticated_data()
    assert str(context.connection_id).encode() in context.authenticated_data()
    assert str(context.record_id).encode() in context.authenticated_data()
    with pytest.raises(FrozenInstanceError):
        context.record_type = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="record type"):
        EncryptionContext(
            workspace_id=uuid4(),
            connection_id=uuid4(),
            record_type=" ",
            record_id=uuid4(),
        )


def test_key_reference_requires_resource_and_immutable_version() -> None:
    reference = KeyReference("projects/p/locations/l/keyRings/r/cryptoKeys/k", "7")
    assert reference.version == "7"
    with pytest.raises(ValueError, match="required"):
        KeyReference("", "7")


class FakeGoogleKmsClient:
    def __init__(self) -> None:
        self.encrypt_request: dict[str, object] | None = None
        self.decrypt_request: dict[str, object] | None = None

    async def encrypt(self, *, request: dict[str, object]) -> object:
        self.encrypt_request = request
        return SimpleNamespace(ciphertext=b"managed-ciphertext")

    async def decrypt(self, *, request: dict[str, object]) -> object:
        self.decrypt_request = request
        return SimpleNamespace(plaintext=b"data-key")


async def test_google_cloud_kms_adapter_uses_version_and_authenticated_data() -> None:
    client = FakeGoogleKmsClient()
    provider = GoogleCloudKmsKeyProvider(client)
    reference = KeyReference("projects/p/locations/l/keyRings/r/cryptoKeys/k", "7")

    wrapped = await provider.wrap_key(
        b"data-key",
        reference,
        authenticated_data=b"tenant-context",
    )
    unwrapped = await provider.unwrap_key(
        wrapped,
        reference,
        authenticated_data=b"tenant-context",
    )

    assert wrapped == b"managed-ciphertext"
    assert unwrapped == b"data-key"
    assert client.encrypt_request == {
        "name": (
            "projects/p/locations/l/keyRings/r/cryptoKeys/k/"
            "cryptoKeyVersions/7"
        ),
        "plaintext": b"data-key",
        "additional_authenticated_data": b"tenant-context",
    }
    assert client.decrypt_request == {
        "name": "projects/p/locations/l/keyRings/r/cryptoKeys/k",
        "ciphertext": b"managed-ciphertext",
        "additional_authenticated_data": b"tenant-context",
    }


async def test_google_cloud_kms_adapter_redacts_provider_failures() -> None:
    class BrokenClient:
        async def encrypt(self, **_: object) -> object:
            raise RuntimeError("provider secret response")

    provider = GoogleCloudKmsKeyProvider(BrokenClient())
    with pytest.raises(KeyProviderUnavailableError) as failure:
        await provider.wrap_key(
            b"secret-data-key",
            KeyReference("managed-key", "1"),
            authenticated_data=b"context",
        )
    assert "provider secret" not in str(failure.value)
    assert "secret-data-key" not in str(failure.value)
