"""Envelope-encryption and failure matrix for the H0-06 prototype."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.architecture.encryption_prototype import (
    DekRotation,
    EncryptedCredential,
    EncryptionError,
    EnvelopeEncryption,
    KeyReference,
    KmsAuthorizationError,
    KmsRole,
    MockKms,
    RotationInterrupted,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
OLD_KEY = KeyReference("atlas-provider-credentials", 1)
NEW_KEY = KeyReference("atlas-provider-credentials", 2)
PLAINTEXT = b"provider-refresh-token-secret"


@pytest.fixture
def kms() -> MockKms:
    return MockKms({OLD_KEY: b"a" * 32, NEW_KEY: b"b" * 32})


@pytest.fixture
def encryption(kms: MockKms) -> EnvelopeEncryption:
    return EnvelopeEncryption(kms)


def encrypted_record(
    encryption: EnvelopeEncryption,
    *,
    connection_id=None,
) -> EncryptedCredential:
    return encryption.encrypt(
        PLAINTEXT,
        workspace_id=uuid4(),
        connection_id=connection_id or uuid4(),
        record_type="provider_credential",
        record_id=uuid4(),
        kms_key=OLD_KEY,
        now=NOW,
    )


def test_fit_encrypt_001_uses_per_record_authenticated_encryption(
    encryption: EnvelopeEncryption,
) -> None:
    """FIT-ENCRYPT-001 retains governed metadata and no plaintext or raw DEK."""

    first = encrypted_record(encryption)
    second = encrypted_record(encryption)

    assert encryption.decrypt(first) == PLAINTEXT
    assert first.algorithm == "AES-256-GCM"
    assert first.format_version == 1
    assert first.ciphertext != second.ciphertext
    assert first.wrapped_dek != second.wrapped_dek
    assert PLAINTEXT not in repr(first).encode()


@pytest.mark.parametrize(
    "change",
    [
        {"workspace_id": uuid4()},
        {"connection_id": uuid4()},
        {"record_type": "different_type"},
        {"record_id": uuid4()},
        {"format_version": 2},
    ],
)
def test_fit_encrypt_002_aad_binds_record_security_context(
    encryption: EnvelopeEncryption,
    change: dict[str, object],
) -> None:
    """FIT-ENCRYPT-002 rejects ciphertext moved to another security context."""

    tampered = replace(encrypted_record(encryption), **change)

    with pytest.raises(EncryptionError, match="format|authentication"):
        encryption.decrypt(tampered)


def test_fit_encrypt_003_runtime_can_decrypt_but_cannot_administer_kms(
    kms: MockKms,
    encryption: EnvelopeEncryption,
) -> None:
    """FIT-ENCRYPT-003 enforces narrow runtime KMS permissions."""

    record = encrypted_record(encryption)
    assert encryption.decrypt(record) == PLAINTEXT

    with pytest.raises(KmsAuthorizationError, match="cannot administer"):
        kms.disable(OLD_KEY, role=KmsRole.RUNTIME)


def test_fit_encrypt_004_kek_rewrap_preserves_credential_ciphertext(
    encryption: EnvelopeEncryption,
) -> None:
    """FIT-ENCRYPT-004 rotates the KEK without decrypting credential content."""

    original = encrypted_record(encryption)
    rotated = encryption.rewrap_kek(
        original,
        new_kms_key=NEW_KEY,
        now=NOW + timedelta(hours=1),
    )

    assert rotated.ciphertext == original.ciphertext
    assert rotated.nonce == original.nonce
    assert rotated.wrapped_dek != original.wrapped_dek
    assert rotated.kms_key == NEW_KEY
    assert encryption.decrypt(rotated) == PLAINTEXT


def test_fit_encrypt_005_dek_replacement_reencrypts_and_verifies(
    encryption: EnvelopeEncryption,
) -> None:
    """FIT-ENCRYPT-005 replaces the DEK while preserving credential meaning."""

    original = encrypted_record(encryption)
    rotated = encryption.replace_dek(
        original,
        now=NOW + timedelta(hours=1),
    )

    assert rotated.ciphertext != original.ciphertext
    assert rotated.wrapped_dek != original.wrapped_dek
    assert rotated.rotated_at == NOW + timedelta(hours=1)
    assert encryption.decrypt(rotated) == PLAINTEXT


def test_fit_encrypt_006_dek_rotation_resumes_without_reprocessing(
    encryption: EnvelopeEncryption,
) -> None:
    """FIT-ENCRYPT-006 checkpoints completed records and resumes after failure."""

    records = tuple(encrypted_record(encryption) for _ in range(3))
    rotation = DekRotation(encryption, records)

    with pytest.raises(RotationInterrupted, match="injected failure"):
        rotation.run(now=NOW + timedelta(hours=1), fail_before=records[1].record_id)

    first_ciphertext = rotation.records[records[0].record_id].ciphertext
    assert rotation.completed == {records[0].record_id}

    rotation.run(now=NOW + timedelta(hours=2))

    assert rotation.completed == {record.record_id for record in records}
    assert rotation.records[records[0].record_id].ciphertext == first_ciphertext
    assert all(
        encryption.decrypt(rotation.records[record.record_id]) == PLAINTEXT
        for record in records
    )


def test_fit_encrypt_007_disabled_key_fails_closed(
    kms: MockKms,
    encryption: EnvelopeEncryption,
) -> None:
    """FIT-ENCRYPT-007 makes credentials inaccessible after emergency key disable."""

    record = encrypted_record(encryption)
    kms.disable(OLD_KEY, role=KmsRole.ADMINISTRATOR)

    with pytest.raises(EncryptionError, match="KMS key is disabled"):
        encryption.decrypt(record)


def test_fit_encrypt_008_emergency_connection_handling_is_complete(
    encryption: EnvelopeEncryption,
) -> None:
    """FIT-ENCRYPT-008 disables access, revokes tokens, and records an incident."""

    connection_id = uuid4()
    record = encrypted_record(encryption, connection_id=connection_id)

    with pytest.raises(EncryptionError, match="incident reference"):
        encryption.emergency_disable_connection(connection_id, incident_reference="")

    encryption.emergency_disable_connection(
        connection_id,
        incident_reference="incident-credential-001",
    )

    with pytest.raises(EncryptionError, match="connection is disabled"):
        encryption.decrypt(record)
    assert connection_id in encryption.revoked_provider_connections
    assert connection_id in encryption.invalidated_clients
    assert encryption.security_incidents == ["incident-credential-001"]


def test_fit_encrypt_009_unknown_format_fails_closed(
    encryption: EnvelopeEncryption,
) -> None:
    """FIT-ENCRYPT-009 prevents silent decryption of unknown record formats."""

    record = replace(encrypted_record(encryption), algorithm="unknown")

    with pytest.raises(EncryptionError, match="unsupported"):
        encryption.decrypt(record)
