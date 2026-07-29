"""Disposable H0 prototype for versioned envelope encryption and rotation."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EncryptionError(ValueError):
    """Raised when an encrypted record cannot be safely processed."""


class KmsAuthorizationError(EncryptionError):
    """Raised when a caller exceeds its narrow KMS permissions."""


class RotationInterrupted(EncryptionError):
    """Raised by the prototype failure injector during resumable rotation."""


class KmsRole(StrEnum):
    RUNTIME = "runtime"
    ROTATOR = "rotator"
    ADMINISTRATOR = "administrator"


@dataclass(frozen=True, slots=True)
class KeyReference:
    key_id: str
    version: int


@dataclass(frozen=True, slots=True)
class EncryptedCredential:
    """Encrypted provider credential without plaintext or an unwrapped DEK."""

    workspace_id: UUID
    connection_id: UUID
    record_type: str
    record_id: UUID
    format_version: int
    algorithm: str
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    kms_key: KeyReference
    encrypted_at: datetime
    rotated_at: datetime | None = None

    def additional_data(self) -> bytes:
        return (
            f"{self.workspace_id}|{self.connection_id}|{self.record_type}|"
            f"{self.record_id}|{self.format_version}"
        ).encode()


class MockKms:
    """Policy-aware stand-in for a managed KMS; keys never leave this boundary."""

    def __init__(self, keys: dict[KeyReference, bytes]) -> None:
        self._keys = dict(keys)
        self._disabled: set[KeyReference] = set()

    def wrap(
        self,
        plaintext_dek: bytes,
        key: KeyReference,
        *,
        role: KmsRole,
    ) -> bytes:
        if role is not KmsRole.ROTATOR:
            raise KmsAuthorizationError("only the rotation role may wrap data keys")
        wrapping_key = self._usable_key(key)
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(wrapping_key).encrypt(
            nonce,
            plaintext_dek,
            self._key_aad(key),
        )

    def unwrap(
        self,
        wrapped_dek: bytes,
        key: KeyReference,
        *,
        role: KmsRole,
    ) -> bytes:
        if role not in {KmsRole.RUNTIME, KmsRole.ROTATOR}:
            raise KmsAuthorizationError("role cannot request credential decryption")
        wrapping_key = self._usable_key(key)
        try:
            return AESGCM(wrapping_key).decrypt(
                wrapped_dek[:12],
                wrapped_dek[12:],
                self._key_aad(key),
            )
        except InvalidTag as error:
            raise EncryptionError("wrapped data key authentication failed") from error

    def disable(self, key: KeyReference, *, role: KmsRole) -> None:
        if role is not KmsRole.ADMINISTRATOR:
            raise KmsAuthorizationError("runtime roles cannot administer KMS keys")
        self._usable_key(key)
        self._disabled.add(key)

    def _usable_key(self, key: KeyReference) -> bytes:
        if key in self._disabled:
            raise EncryptionError("KMS key is disabled")
        try:
            return self._keys[key]
        except KeyError as error:
            raise EncryptionError("KMS key is unavailable") from error

    @staticmethod
    def _key_aad(key: KeyReference) -> bytes:
        return f"{key.key_id}|{key.version}".encode()


class EnvelopeEncryption:
    """Per-record authenticated encryption with independently wrapped DEKs."""

    FORMAT_VERSION = 1
    ALGORITHM = "AES-256-GCM"

    def __init__(self, kms: MockKms) -> None:
        self._kms = kms
        self._disabled_connections: set[UUID] = set()
        self.security_incidents: list[str] = []
        self.revoked_provider_connections: set[UUID] = set()
        self.invalidated_clients: set[UUID] = set()

    def encrypt(
        self,
        plaintext: bytes,
        *,
        workspace_id: UUID,
        connection_id: UUID,
        record_type: str,
        record_id: UUID,
        kms_key: KeyReference,
        now: datetime,
    ) -> EncryptedCredential:
        self._ensure_connection_enabled(connection_id)
        dek = AESGCM.generate_key(bit_length=256)
        nonce = secrets.token_bytes(12)
        skeleton = EncryptedCredential(
            workspace_id=workspace_id,
            connection_id=connection_id,
            record_type=record_type,
            record_id=record_id,
            format_version=self.FORMAT_VERSION,
            algorithm=self.ALGORITHM,
            ciphertext=b"",
            nonce=nonce,
            wrapped_dek=b"",
            kms_key=kms_key,
            encrypted_at=now,
        )
        return replace(
            skeleton,
            ciphertext=AESGCM(dek).encrypt(
                nonce,
                plaintext,
                skeleton.additional_data(),
            ),
            wrapped_dek=self._kms.wrap(dek, kms_key, role=KmsRole.ROTATOR),
        )

    def decrypt(self, record: EncryptedCredential) -> bytes:
        self._validate_format(record)
        self._ensure_connection_enabled(record.connection_id)
        dek = self._kms.unwrap(
            record.wrapped_dek,
            record.kms_key,
            role=KmsRole.RUNTIME,
        )
        try:
            return AESGCM(dek).decrypt(
                record.nonce,
                record.ciphertext,
                record.additional_data(),
            )
        except InvalidTag as error:
            raise EncryptionError("credential authentication failed") from error

    def rewrap_kek(
        self,
        record: EncryptedCredential,
        *,
        new_kms_key: KeyReference,
        now: datetime,
    ) -> EncryptedCredential:
        dek = self._kms.unwrap(
            record.wrapped_dek,
            record.kms_key,
            role=KmsRole.ROTATOR,
        )
        return replace(
            record,
            wrapped_dek=self._kms.wrap(
                dek,
                new_kms_key,
                role=KmsRole.ROTATOR,
            ),
            kms_key=new_kms_key,
            rotated_at=now,
        )

    def replace_dek(
        self,
        record: EncryptedCredential,
        *,
        now: datetime,
    ) -> EncryptedCredential:
        plaintext = self.decrypt(record)
        replacement = self.encrypt(
            plaintext,
            workspace_id=record.workspace_id,
            connection_id=record.connection_id,
            record_type=record.record_type,
            record_id=record.record_id,
            kms_key=record.kms_key,
            now=record.encrypted_at,
        )
        return replace(replacement, rotated_at=now)

    def emergency_disable_connection(
        self,
        connection_id: UUID,
        *,
        incident_reference: str,
    ) -> None:
        if not incident_reference.strip():
            raise EncryptionError("emergency handling requires an incident reference")
        self._disabled_connections.add(connection_id)
        self.revoked_provider_connections.add(connection_id)
        self.invalidated_clients.add(connection_id)
        self.security_incidents.append(incident_reference)

    def _validate_format(self, record: EncryptedCredential) -> None:
        if (
            record.format_version != self.FORMAT_VERSION
            or record.algorithm != self.ALGORITHM
        ):
            raise EncryptionError("unsupported credential encryption format")

    def _ensure_connection_enabled(self, connection_id: UUID) -> None:
        if connection_id in self._disabled_connections:
            raise EncryptionError("provider connection is disabled")


class DekRotation:
    """Checkpointed DEK replacement that safely resumes after interruption."""

    def __init__(
        self,
        encryption: EnvelopeEncryption,
        records: tuple[EncryptedCredential, ...],
    ) -> None:
        self._encryption = encryption
        self.records = {record.record_id: record for record in records}
        self.completed: set[UUID] = set()

    def run(
        self,
        *,
        now: datetime,
        fail_before: UUID | None = None,
    ) -> None:
        for record_id in tuple(self.records):
            if record_id in self.completed:
                continue
            if record_id == fail_before:
                raise RotationInterrupted("injected failure before DEK replacement")
            self.records[record_id] = self._encryption.replace_dek(
                self.records[record_id],
                now=now,
            )
            self.completed.add(record_id)
