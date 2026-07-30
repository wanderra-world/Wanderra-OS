"""Transactional H2-02 credential inventory, shadow migration, and lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.connection_credentials.contracts import (
    CredentialAuthorizationError,
    CredentialMigrationError,
    CredentialStateError,
    CredentialStatus,
    InventoryStatus,
    InventorySummary,
    ShadowMigrationCommand,
    canonical_credential_payload,
    credential_record_type,
    normalize_scopes,
)
from app.connection_credentials.models import (
    ConnectionCredential,
    CredentialMigrationInventory,
)
from app.connection_credentials.repository import ConnectionCredentialRepository
from app.connections.models import Connection
from app.connections.repository import ConnectionRepository
from app.connections.service import H1ConnectionAuthorizer
from app.encryption import (
    EncryptionError,
    EnvelopeEncryptionService,
    KeyProvider,
    KeyReference,
)
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent


class CredentialAuthorizer(Protocol):
    async def authorize(
        self, context: ExecutionContext, permission_key: str
    ) -> bool: ...


class LegacyShadowLinker(Protocol):
    async def link_verified_shadow(
        self,
        *,
        source_system: str,
        source_record_id: str,
        workspace_id: uuid.UUID,
        envelope_id: uuid.UUID,
        checksum: str,
        verified_at: datetime,
    ) -> None: ...


class ConnectionCredentialService:
    """Manage new custody metadata while Phase 1 remains authoritative."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        key_provider: KeyProvider,
        authorizer: CredentialAuthorizer | None = None,
        legacy_linker: LegacyShadowLinker | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._keys = key_provider
        self._authorizer = authorizer or H1ConnectionAuthorizer(session)
        self._legacy_linker = legacy_linker
        self._repository = ConnectionCredentialRepository(session, context)
        self._connections = ConnectionRepository(session, context)
        self._encryption = EnvelopeEncryptionService(session, context, key_provider)
        self._audit = AuditWriterService(session, context)

    async def shadow_migrate(
        self,
        command: ShadowMigrationCommand,
        *,
        key_reference: KeyReference,
        now: datetime | None = None,
    ) -> ConnectionCredential:
        await self._require_authorized()
        connection = await self._require_connection(command.connection_id)
        if connection.provider_key != command.provider_key:
            raise CredentialMigrationError("credential provider does not match connection")
        snapshot = command.snapshot
        await self._repository.lock_inventory_source(
            snapshot.source_system,
            snapshot.source_record_id,
        )
        item = await self._repository.inventory_item(
            snapshot.source_system,
            snapshot.source_record_id,
            for_update=True,
        )
        if item is not None:
            if item.source_checksum != snapshot.source_checksum:
                raise CredentialMigrationError("legacy credential changed after inventory")
            item.attempt_count += 1
            if item.status == InventoryStatus.VERIFIED.value:
                assert item.credential_id is not None
                existing = await self._repository.get_credential(item.credential_id)
                if existing is None:
                    raise CredentialMigrationError("verified credential is unavailable")
                return existing
        else:
            item = await self._repository.add_inventory(
                CredentialMigrationInventory(
                    workspace_id=self._context.tenant.workspace_id,
                    connection_id=connection.id,
                    source_system=snapshot.source_system,
                    source_record_id=snapshot.source_record_id,
                    source_checksum=snapshot.source_checksum,
                    scopes=list(normalize_scopes(snapshot.scopes)),
                    status=InventoryStatus.ELIGIBLE.value,
                    attempt_count=1,
                )
            )

        missing = set(normalize_scopes(command.required_scopes)) - set(
            normalize_scopes(snapshot.scopes)
        )
        if missing:
            item.status = InventoryStatus.REAUTHORIZATION_REQUIRED.value
            item.exception_code = "required_scope_missing"
            await self._record_event(
                target_id=item.id,
                action="connection.shadow_reauthorization_required",
                details={"connection_id": str(connection.id), "reason": "scope_gap"},
                sequence=item.attempt_count,
            )
            raise CredentialMigrationError("credential requires additional authorization")

        latest = await self._repository.latest_generation(
            connection.id,
            command.credential_kind,
            for_update=True,
        )
        generation = 1 if latest is None else latest.generation + 1
        credential_id = uuid.uuid4()
        canonical = canonical_credential_payload(snapshot.plaintext)
        record_type = credential_record_type(
            provider_key=connection.provider_key,
            credential_kind=command.credential_kind,
            generation=generation,
        )
        try:
            envelope = await self._encryption.encrypt(
                canonical,
                connection_id=connection.id,
                record_type=record_type,
                record_id=credential_id,
                key_reference=key_reference,
                legacy_source=snapshot.source_system,
                legacy_ciphertext=snapshot.legacy_ciphertext,
                now=now,
            )
            item.status = InventoryStatus.MIGRATED.value
            credential = await self._repository.add_credential(
                ConnectionCredential(
                    workspace_id=self._context.tenant.workspace_id,
                    id=credential_id,
                    connection_id=connection.id,
                    provider_key=connection.provider_key,
                    credential_kind=command.credential_kind,
                    generation=generation,
                    version=1,
                    envelope_id=envelope.id,
                    status=CredentialStatus.SHADOW_VERIFIED.value,
                    scopes=list(normalize_scopes(snapshot.scopes)),
                    source_system=snapshot.source_system,
                    source_record_id=snapshot.source_record_id,
                    source_checksum=snapshot.source_checksum,
                    expires_at=snapshot.expires_at,
                    verified_at=now or datetime.now(UTC),
                )
            )
            await self._encryption.verify_legacy_shadow(
                envelope_id=envelope.id,
                legacy_plaintext=canonical,
                legacy_ciphertext=snapshot.legacy_ciphertext,
                now=now,
            )
        except EncryptionError as error:
            item.status = InventoryStatus.FAILED.value
            item.exception_code = "encryption_failed"
            raise CredentialMigrationError("credential shadow migration failed") from error

        verified_at = credential.verified_at or datetime.now(UTC)
        item.credential_id = credential.id
        item.status = InventoryStatus.VERIFIED.value
        item.exception_code = None
        item.verified_at = verified_at
        if self._legacy_linker is not None:
            await self._legacy_linker.link_verified_shadow(
                source_system=snapshot.source_system,
                source_record_id=snapshot.source_record_id,
                workspace_id=credential.workspace_id,
                envelope_id=envelope.id,
                checksum=snapshot.source_checksum,
                verified_at=verified_at,
            )
        await self._record_event(
            target_id=credential.id,
            action="connection.shadow_verified",
            details={
                "connection_id": str(connection.id),
                "provider_key": connection.provider_key,
                "kind": credential.credential_kind,
                "generation": credential.generation,
            },
            sequence=credential.version,
        )
        return credential

    async def rotate(
        self,
        *,
        credential_id: uuid.UUID,
        replacement_plaintext: bytes,
        key_reference: KeyReference,
        scopes: tuple[str, ...],
        now: datetime | None = None,
    ) -> ConnectionCredential:
        await self._require_authorized()
        current = await self._repository.get_credential(
            credential_id, for_update=True
        )
        if current is None or current.status not in {
            CredentialStatus.SHADOW_VERIFIED.value,
            CredentialStatus.ACTIVE.value,
        }:
            raise CredentialStateError("credential cannot be rotated")
        changed_at = now or datetime.now(UTC)
        next_id = uuid.uuid4()
        generation = current.generation + 1
        envelope = await self._encryption.encrypt(
            canonical_credential_payload(replacement_plaintext),
            connection_id=current.connection_id,
            record_type=credential_record_type(
                provider_key=current.provider_key,
                credential_kind=current.credential_kind,
                generation=generation,
            ),
            record_id=next_id,
            key_reference=key_reference,
            now=changed_at,
        )
        replacement = await self._repository.add_credential(
            ConnectionCredential(
                workspace_id=current.workspace_id,
                id=next_id,
                connection_id=current.connection_id,
                provider_key=current.provider_key,
                credential_kind=current.credential_kind,
                generation=generation,
                version=1,
                envelope_id=envelope.id,
                status=CredentialStatus.SHADOW_VERIFIED.value,
                scopes=list(normalize_scopes(scopes)),
                verified_at=changed_at,
            )
        )
        current.status = CredentialStatus.REVOKED.value
        current.revoked_at = changed_at
        current.version += 1
        await self._record_event(
            target_id=replacement.id,
            action="connection.shadow_rotated",
            details={
                "connection_id": str(current.connection_id),
                "kind": current.credential_kind,
                "generation": generation,
            },
            sequence=replacement.version,
        )
        return replacement

    async def emergency_disable(
        self,
        *,
        credential_id: uuid.UUID,
        incident_reference: str,
        now: datetime | None = None,
    ) -> ConnectionCredential:
        await self._require_authorized()
        credential = await self._repository.get_credential(
            credential_id, for_update=True
        )
        if credential is None or credential.status in {
            CredentialStatus.REVOKED.value,
            CredentialStatus.DISABLED.value,
        }:
            raise CredentialStateError("credential cannot be disabled")
        changed_at = now or datetime.now(UTC)
        await self._encryption.emergency_disable(
            envelope_id=credential.envelope_id,
            incident_reference=incident_reference,
            now=changed_at,
        )
        credential.status = CredentialStatus.DISABLED.value
        credential.disabled_at = changed_at
        credential.version += 1
        await self._record_event(
            target_id=credential.id,
            action="connection.shadow_disabled",
            details={
                "connection_id": str(credential.connection_id),
                "incident_reference": incident_reference,
            },
            sequence=credential.version,
        )
        return credential

    async def revoke(
        self,
        *,
        credential_id: uuid.UUID,
        now: datetime | None = None,
    ) -> ConnectionCredential:
        return await self._make_unavailable(
            credential_id=credential_id,
            target=CredentialStatus.REVOKED,
            reason="revoked",
            now=now,
        )

    async def require_reauthorization(
        self,
        *,
        credential_id: uuid.UUID,
        reason: str,
        now: datetime | None = None,
    ) -> ConnectionCredential:
        if reason not in {"expired", "scope_gap", "provider_revoked"}:
            raise CredentialStateError("reauthorization reason is invalid")
        return await self._make_unavailable(
            credential_id=credential_id,
            target=CredentialStatus.REAUTHORIZATION_REQUIRED,
            reason=reason,
            now=now,
        )

    async def inventory_summary(self) -> InventorySummary:
        await self._require_authorized(permission_key="read_content")
        return await self._repository.summary()

    async def _make_unavailable(
        self,
        *,
        credential_id: uuid.UUID,
        target: CredentialStatus,
        reason: str,
        now: datetime | None,
    ) -> ConnectionCredential:
        await self._require_authorized()
        credential = await self._repository.get_credential(
            credential_id, for_update=True
        )
        if credential is None or credential.status not in {
            CredentialStatus.SHADOW_VERIFIED.value,
            CredentialStatus.ACTIVE.value,
        }:
            raise CredentialStateError("credential cannot change availability")
        changed_at = now or datetime.now(UTC)
        await self._encryption.emergency_disable(
            envelope_id=credential.envelope_id,
            incident_reference=f"availability-{reason}",
            now=changed_at,
        )
        credential.status = target.value
        credential.version += 1
        if target is CredentialStatus.REVOKED:
            credential.revoked_at = changed_at
        await self._record_event(
            target_id=credential.id,
            action=f"connection.shadow_{target.value}",
            details={
                "connection_id": str(credential.connection_id),
                "reason": reason,
            },
            sequence=credential.version,
        )
        return credential

    async def _require_connection(self, connection_id: uuid.UUID) -> Connection:
        connection = await self._connections.get(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=connection_id,
        )
        if connection is None or connection.status in {"revoked", "closed"}:
            raise CredentialMigrationError("connection is unavailable")
        return connection

    async def _require_authorized(
        self, *, permission_key: str = "manage_workspace"
    ) -> None:
        if not await self._authorizer.authorize(self._context, permission_key):
            raise CredentialAuthorizationError(
                "workspace credential administration is denied"
            )

    async def _record_event(
        self,
        *,
        target_id: uuid.UUID,
        action: str,
        details: dict[str, object],
        sequence: int,
    ) -> None:
        audit = await self._audit.write(
            AuditInput(
                action=action,
                target_type="connection_secret",
                target_id=target_id,
                outcome="success",
                details=details,
                classification="restricted",
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=self._context.tenant.workspace_id,
                id=uuid.uuid4(),
                event_type=action,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="connection_secret",
                aggregate_id=target_id,
                aggregate_sequence=sequence,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="restricted",
                payload={"audit_event_id": str(audit.id), **details},
            )
        )
        await self._session.flush()
