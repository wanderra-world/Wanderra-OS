"""Per-record AES-GCM envelope encryption backed by a managed KMS port."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.ext.asyncio import AsyncSession

from app.encryption.contracts import (
    ENVELOPE_ALGORITHM,
    ENVELOPE_FORMAT_VERSION,
    EncryptedEnvelopeData,
    EncryptionContext,
    EncryptionError,
    KeyProvider,
    KeyProviderUnavailableError,
    KeyReference,
)
from app.encryption.models import EncryptedEnvelope
from app.encryption.repository import EncryptionRepository
from app.execution_context import ExecutionContext
from app.tenancy.models import AuditEvent, OutboxEvent


class EnvelopeEncryptionService:
    """Encrypt, decrypt, rotate, quarantine, and audit credential envelopes."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        key_provider: KeyProvider,
    ) -> None:
        self._session = session
        self._context = context
        self._keys = key_provider
        self._repository = EncryptionRepository(session, context)

    async def encrypt(
        self,
        plaintext: bytes,
        *,
        connection_id: uuid.UUID,
        record_type: str,
        record_id: uuid.UUID,
        key_reference: KeyReference,
        legacy_source: str | None = None,
        legacy_ciphertext: bytes | None = None,
        now: datetime | None = None,
    ) -> EncryptedEnvelope:
        encrypted_at = now or datetime.now(UTC)
        context = EncryptionContext(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=connection_id,
            record_type=record_type,
            record_id=record_id,
        )
        data = await self._encrypt_data(
            plaintext,
            context=context,
            key_reference=key_reference,
            now=encrypted_at,
        )
        envelope = EncryptedEnvelope(
            workspace_id=context.workspace_id,
            connection_id=context.connection_id,
            record_type=context.record_type,
            record_id=context.record_id,
            format_version=context.format_version,
            algorithm=data.algorithm,
            ciphertext=data.ciphertext,
            nonce=data.nonce,
            wrapped_dek=data.wrapped_dek,
            kms_key_resource=key_reference.resource,
            kms_key_version=key_reference.version,
            checksum=data.checksum,
            encrypted_at=encrypted_at,
            legacy_source=legacy_source,
            legacy_checksum=(
                hashlib.sha256(legacy_ciphertext).hexdigest()
                if legacy_ciphertext is not None
                else None
            ),
        )
        await self._repository.add(envelope)
        await self._audit(
            envelope,
            action="encryption.envelope_created",
            outcome="success",
        )
        return envelope

    async def decrypt(self, envelope: EncryptedEnvelope) -> bytes:
        self._repository.require_workspace(envelope.workspace_id)
        if envelope.status != "active":
            raise EncryptionError("encrypted envelope is unavailable")
        data = self._to_data(envelope)
        try:
            dek = await self._keys.unwrap_key(
                data.wrapped_dek,
                data.key_reference,
                authenticated_data=data.context.authenticated_data(),
            )
            plaintext = AESGCM(dek).decrypt(
                data.nonce,
                data.ciphertext,
                data.context.authenticated_data(),
            )
        except (InvalidTag, KeyProviderUnavailableError) as error:
            raise EncryptionError("encrypted envelope authentication failed") from error
        if hashlib.sha256(data.ciphertext).hexdigest() != data.checksum:
            raise EncryptionError("encrypted envelope checksum failed")
        return plaintext

    async def rewrap(
        self,
        *,
        envelope_id: uuid.UUID,
        new_key_reference: KeyReference,
        rotation_request_id: uuid.UUID,
        now: datetime | None = None,
    ) -> EncryptedEnvelope:
        envelope = await self._locked(envelope_id)
        if (
            envelope.rotation_request_id == rotation_request_id
            and envelope.kms_key_resource == new_key_reference.resource
            and envelope.kms_key_version == new_key_reference.version
            and envelope.status == "active"
        ):
            return envelope
        data = self._to_data(envelope)
        try:
            dek = await self._keys.unwrap_key(
                data.wrapped_dek,
                data.key_reference,
                authenticated_data=data.context.authenticated_data(),
            )
            envelope.wrapped_dek = await self._keys.wrap_key(
                dek,
                new_key_reference,
                authenticated_data=data.context.authenticated_data(),
            )
        except KeyProviderUnavailableError as error:
            await self._quarantine(envelope, "key_provider_failure", now=now)
            raise EncryptionError("key rotation failed closed") from error
        envelope.kms_key_resource = new_key_reference.resource
        envelope.kms_key_version = new_key_reference.version
        envelope.rotation_request_id = rotation_request_id
        envelope.generation += 1
        envelope.rotated_at = now or datetime.now(UTC)
        envelope.status = "active"
        await self._audit(
            envelope,
            action="encryption.kek_rewrapped",
            outcome="success",
        )
        await self._session.flush()
        return envelope

    async def replace_data_key(
        self,
        *,
        envelope_id: uuid.UUID,
        rotation_request_id: uuid.UUID,
        now: datetime | None = None,
    ) -> EncryptedEnvelope:
        envelope = await self._locked(envelope_id)
        if (
            envelope.rotation_request_id == rotation_request_id
            and envelope.status == "active"
        ):
            return envelope
        plaintext = await self.decrypt(envelope)
        replacement = await self._encrypt_data(
            plaintext,
            context=self._to_data(envelope).context,
            key_reference=KeyReference(
                envelope.kms_key_resource,
                envelope.kms_key_version,
            ),
            now=now or datetime.now(UTC),
        )
        envelope.ciphertext = replacement.ciphertext
        envelope.nonce = replacement.nonce
        envelope.wrapped_dek = replacement.wrapped_dek
        envelope.checksum = replacement.checksum
        envelope.rotation_request_id = rotation_request_id
        envelope.generation += 1
        envelope.rotated_at = now or datetime.now(UTC)
        await self._audit(
            envelope,
            action="encryption.dek_replaced",
            outcome="success",
        )
        await self._session.flush()
        return envelope

    async def emergency_disable(
        self,
        *,
        envelope_id: uuid.UUID,
        incident_reference: str,
        now: datetime | None = None,
    ) -> EncryptedEnvelope:
        if not incident_reference.strip():
            raise EncryptionError("incident reference is required")
        envelope = await self._locked(envelope_id)
        envelope.status = "disabled"
        envelope.generation += 1
        envelope.quarantined_at = now or datetime.now(UTC)
        envelope.quarantine_reason = "incident_disable"
        await self._audit(
            envelope,
            action="encryption.envelope_disabled",
            outcome="success",
            details={"incident_reference": incident_reference},
        )
        await self._session.flush()
        return envelope

    async def verify_legacy_shadow(
        self,
        *,
        envelope_id: uuid.UUID,
        legacy_plaintext: bytes,
        legacy_ciphertext: bytes,
        now: datetime | None = None,
    ) -> EncryptedEnvelope:
        """Prove old and new ciphertext decrypt equivalently without cutover."""
        envelope = await self._locked(envelope_id)
        envelope_plaintext = await self.decrypt(envelope)
        if not hmac.compare_digest(envelope_plaintext, legacy_plaintext):
            await self._quarantine(
                envelope,
                "shadow_verification_mismatch",
                now=now,
            )
            raise EncryptionError("shadow verification failed")
        envelope.legacy_checksum = hashlib.sha256(legacy_ciphertext).hexdigest()
        envelope.shadow_verified_at = now or datetime.now(UTC)
        envelope.generation += 1
        await self._audit(
            envelope,
            action="encryption.shadow_verified",
            outcome="success",
        )
        await self._session.flush()
        return envelope

    async def _encrypt_data(
        self,
        plaintext: bytes,
        *,
        context: EncryptionContext,
        key_reference: KeyReference,
        now: datetime,
    ) -> EncryptedEnvelopeData:
        dek = AESGCM.generate_key(bit_length=256)
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(dek).encrypt(
            nonce,
            plaintext,
            context.authenticated_data(),
        )
        try:
            wrapped_dek = await self._keys.wrap_key(
                dek,
                key_reference,
                authenticated_data=context.authenticated_data(),
            )
        except KeyProviderUnavailableError as error:
            raise EncryptionError("managed key provider is unavailable") from error
        return EncryptedEnvelopeData(
            context=context,
            algorithm=ENVELOPE_ALGORITHM,
            ciphertext=ciphertext,
            nonce=nonce,
            wrapped_dek=wrapped_dek,
            key_reference=key_reference,
            checksum=hashlib.sha256(ciphertext).hexdigest(),
            encrypted_at=now,
        )

    async def _locked(self, envelope_id: uuid.UUID) -> EncryptedEnvelope:
        envelope = await self._repository.get(
            workspace_id=self._context.tenant.workspace_id,
            envelope_id=envelope_id,
            for_update=True,
        )
        if envelope is None:
            raise EncryptionError("encrypted envelope does not exist")
        if envelope.status in {"disabled", "quarantined"}:
            raise EncryptionError("encrypted envelope is unavailable")
        return envelope

    async def _quarantine(
        self,
        envelope: EncryptedEnvelope,
        reason: str,
        *,
        now: datetime | None,
    ) -> None:
        envelope.status = "quarantined"
        envelope.generation += 1
        envelope.quarantined_at = now or datetime.now(UTC)
        envelope.quarantine_reason = reason
        await self._audit(
            envelope,
            action="encryption.envelope_quarantined",
            outcome="denied",
            details={"reason": reason},
        )
        await self._session.flush()

    async def _audit(
        self,
        envelope: EncryptedEnvelope,
        *,
        action: str,
        outcome: str,
        details: dict[str, str] | None = None,
    ) -> None:
        audit_id = uuid.uuid4()
        safe_details = {
            **self._context.audit_references(),
            "envelope_generation": str(envelope.generation),
            "kms_key_version": envelope.kms_key_version,
            **(details or {}),
        }
        self._session.add(
            AuditEvent(
                workspace_id=envelope.workspace_id,
                id=audit_id,
                actor_type="user",
                actor_id=self._context.actor.actor_id,
                action=action,
                target_type="encrypted_envelope",
                target_id=envelope.id,
                outcome=outcome,
                details=safe_details,
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=envelope.workspace_id,
                id=uuid.uuid4(),
                event_type=action,
                aggregate_type="encrypted_envelope",
                aggregate_id=envelope.id,
                aggregate_sequence=envelope.generation,
                payload={"audit_event_id": str(audit_id), **safe_details},
            )
        )

    @staticmethod
    def _to_data(envelope: EncryptedEnvelope) -> EncryptedEnvelopeData:
        if (
            envelope.format_version != ENVELOPE_FORMAT_VERSION
            or envelope.algorithm != ENVELOPE_ALGORITHM
        ):
            raise EncryptionError("unsupported encrypted envelope format")
        return EncryptedEnvelopeData(
            context=EncryptionContext(
                workspace_id=envelope.workspace_id,
                connection_id=envelope.connection_id,
                record_type=envelope.record_type,
                record_id=envelope.record_id,
                format_version=envelope.format_version,
            ),
            algorithm=envelope.algorithm,
            ciphertext=envelope.ciphertext,
            nonce=envelope.nonce,
            wrapped_dek=envelope.wrapped_dek,
            key_reference=KeyReference(
                envelope.kms_key_resource,
                envelope.kms_key_version,
            ),
            checksum=envelope.checksum,
            encrypted_at=envelope.encrypted_at,
        )
