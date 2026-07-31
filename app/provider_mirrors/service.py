"""Transactional H2-04 mirror observation and decision service."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.connections.repository import ConnectionRepository
from app.connections.service import H1ConnectionAuthorizer
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.provider_mirrors.contracts import (
    AuthorityPolicy,
    ComparisonDecision,
    ComparisonDirection,
    ConflictReason,
    MirrorCreate,
    MirrorState,
    ProviderMirrorAuthorizationError,
    ProviderMirrorError,
    ProviderMirrorReplayError,
    ProviderObservation,
    decide_inbound,
    decide_outbound,
    normalized_identifier,
)
from app.provider_mirrors.models import (
    ProviderExternalReference,
    ProviderMirror,
    ProviderMirrorComparison,
    ProviderMirrorConflict,
)
from app.provider_mirrors.repository import ProviderMirrorRepository
from app.tenancy.models import OutboxEvent


class MirrorAuthorizer(Protocol):
    async def authorize(
        self, context: ExecutionContext, permission_key: str
    ) -> bool: ...


class ProviderMirrorService:
    """Persist observations and decisions without invoking any provider."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: MirrorAuthorizer | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._authorizer = authorizer or H1ConnectionAuthorizer(session)
        self._repository = ProviderMirrorRepository(session, context)
        self._connections = ConnectionRepository(session, context)
        self._audit = AuditWriterService(session, context)

    async def observe_new(
        self,
        command: MirrorCreate,
        *,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ProviderMirror:
        await self._require_authorized()
        command = command.validated()
        key = self._key(idempotency_key)
        request_digest = self._digest(
            {
                "kind": "new",
                "connection_id": str(command.connection_id),
                "resource_type": command.resource_type,
                "external_id": command.external_id,
                "authority": command.authority.value,
                "field_authority": {
                    field: authority.value
                    for field, authority in command.field_authority.items()
                },
                "observation": self._observation_payload(command.observation),
            }
        )
        await self._repository.lock_idempotency(key)
        replay = await self._repository.comparison(key)
        if replay is not None:
            return await self._replayed_mirror(replay, request_digest)
        connection = await self._connections.get(
            workspace_id=self._context.tenant.workspace_id,
            connection_id=command.connection_id,
        )
        if connection is None or connection.status in {"revoked", "closed"}:
            raise ProviderMirrorError("mirror connection is unavailable")
        changed_at = now or datetime.now(UTC)
        observation = command.observation
        state = (
            MirrorState.TOMBSTONED
            if observation.deleted
            else MirrorState.SYNCED
        )
        mirror = await self._repository.add_mirror(
            ProviderMirror(
                workspace_id=self._context.tenant.workspace_id,
                id=command.mirror_id,
                connection_id=command.connection_id,
                resource_type=command.resource_type,
                external_id=command.external_id,
                provider_version=observation.provider_version,
                etag=observation.etag,
                provider_updated_at=observation.provider_updated_at,
                normalized_hash=observation.normalized_hash,
                raw_payload_reference=observation.raw_payload_reference,
                raw_payload_owner=observation.raw_payload_owner,
                authority=command.authority.value,
                field_authority={
                    field: authority.value
                    for field, authority in command.field_authority.items()
                },
                sync_state=state.value,
                tombstoned_at=changed_at if observation.deleted else None,
                version=1,
                created_at=changed_at,
                updated_at=changed_at,
            )
        )
        await self._repository.add_reference(
            ProviderExternalReference(
                workspace_id=mirror.workspace_id,
                id=command.external_reference_id,
                mirror_id=mirror.id,
                connection_id=mirror.connection_id,
                resource_type=mirror.resource_type,
                external_id=mirror.external_id,
                version=1,
                created_at=changed_at,
            )
        )
        await self._record_comparison(
            mirror,
            direction=ComparisonDirection.INBOUND,
            idempotency_key=key,
            request_digest=request_digest,
            decision=(
                ComparisonDecision.TOMBSTONE
                if observation.deleted
                else ComparisonDecision.APPLY
            ),
            observation=observation,
            conflict_reason=None,
            now=changed_at,
        )
        await self._record_event(mirror, "provider_mirror.created")
        return mirror

    async def observe(
        self,
        *,
        mirror_id: uuid.UUID,
        observation: ProviderObservation,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ProviderMirror:
        await self._require_authorized()
        observation = observation.validated()
        key = self._key(idempotency_key)
        request_digest = self._digest(
            {
                "kind": "inbound",
                "mirror_id": str(mirror_id),
                "observation": self._observation_payload(observation),
            }
        )
        await self._repository.lock_idempotency(key)
        replay = await self._repository.comparison(key)
        if replay is not None:
            return await self._replayed_mirror(replay, request_digest)
        mirror = await self._require_mirror(mirror_id, for_update=True)
        result = decide_inbound(
            authority=AuthorityPolicy(mirror.authority),
            current_version=mirror.provider_version,
            current_hash=mirror.normalized_hash,
            observation=observation,
        )
        changed_at = now or datetime.now(UTC)
        if result.decision is ComparisonDecision.APPLY:
            self._apply_observation(mirror, observation, changed_at)
        elif result.decision is ComparisonDecision.TOMBSTONE:
            self._apply_observation(mirror, observation, changed_at)
            mirror.sync_state = MirrorState.TOMBSTONED.value
            mirror.tombstoned_at = changed_at
        elif result.decision is ComparisonDecision.CONFLICT:
            mirror.sync_state = MirrorState.CONFLICT.value
            mirror.version += 1
            mirror.updated_at = changed_at
            await self._ensure_conflict(
                mirror,
                reason=result.conflict_reason
                or ConflictReason.AMBIGUOUS_INBOUND,
                provider_hash=observation.normalized_hash,
                provider_version=observation.provider_version,
                now=changed_at,
            )
        await self._record_comparison(
            mirror,
            direction=ComparisonDirection.INBOUND,
            idempotency_key=key,
            request_digest=request_digest,
            decision=result.decision,
            observation=observation,
            conflict_reason=result.conflict_reason,
            now=changed_at,
        )
        if result.decision is not ComparisonDecision.NO_CHANGE:
            await self._record_event(
                mirror, f"provider_mirror.{result.decision.value}"
            )
        return mirror

    async def decide_outbound(
        self,
        *,
        mirror_id: uuid.UUID,
        expected_provider_version: str,
        proposed_hash: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ProviderMirrorComparison:
        await self._require_authorized()
        if len(proposed_hash) != 64:
            raise ProviderMirrorError("proposed normalized hash is invalid")
        key = self._key(idempotency_key)
        request_digest = self._digest(
            {
                "kind": "outbound",
                "mirror_id": str(mirror_id),
                "expected_provider_version": expected_provider_version,
                "proposed_hash": proposed_hash,
            }
        )
        await self._repository.lock_idempotency(key)
        replay = await self._repository.comparison(key)
        if replay is not None:
            if replay.request_digest != request_digest:
                raise ProviderMirrorReplayError(
                    "mirror idempotency key was reused with changed input"
                )
            return replay
        mirror = await self._require_mirror(mirror_id, for_update=True)
        result = decide_outbound(
            authority=AuthorityPolicy(mirror.authority),
            current_version=mirror.provider_version,
            expected_version=expected_provider_version,
        )
        changed_at = now or datetime.now(UTC)
        if result.decision is ComparisonDecision.REFRESH_REQUIRED:
            mirror.sync_state = MirrorState.CONFLICT.value
            mirror.version += 1
            mirror.updated_at = changed_at
            await self._ensure_conflict(
                mirror,
                reason=ConflictReason.PRECONDITION_FAILED,
                provider_hash=mirror.normalized_hash,
                provider_version=mirror.provider_version,
                now=changed_at,
                atlas_hash=proposed_hash,
            )
        comparison = await self._record_comparison(
            mirror,
            direction=ComparisonDirection.OUTBOUND,
            idempotency_key=key,
            request_digest=request_digest,
            decision=result.decision,
            observation=ProviderObservation(
                provider_version=expected_provider_version,
                etag=None,
                provider_updated_at=changed_at,
                normalized_hash=proposed_hash,
                deleted=False,
            ),
            conflict_reason=result.conflict_reason,
            now=changed_at,
        )
        await self._record_event(mirror, "provider_mirror.outbound_decided")
        return comparison

    async def link_canonical(
        self,
        *,
        mirror_id: uuid.UUID,
        reference_type: str,
        reference_id: uuid.UUID,
        approval_reference: str,
        now: datetime | None = None,
    ) -> ProviderExternalReference:
        await self._require_authorized()
        reference_type = normalized_identifier(
            reference_type, field="canonical reference type"
        )
        if not approval_reference.strip():
            raise ProviderMirrorError("approved command reference is required")
        mirror = await self._require_mirror(mirror_id, for_update=True)
        reference = await self._repository.reference(mirror.id, for_update=True)
        if reference is None:
            raise ProviderMirrorError("external reference is unavailable")
        if reference.canonical_reference_id is not None:
            if (
                reference.canonical_reference_type == reference_type
                and reference.canonical_reference_id == reference_id
            ):
                return reference
            raise ProviderMirrorError("canonical reference is already linked")
        reference.canonical_reference_type = reference_type
        reference.canonical_reference_id = reference_id
        reference.approval_reference = approval_reference
        reference.linked_at = now or datetime.now(UTC)
        reference.version += 1
        mirror.version += 1
        mirror.updated_at = reference.linked_at
        await self._record_event(mirror, "provider_mirror.canonical_linked")
        return reference

    async def resolve_conflict(
        self,
        *,
        conflict_id: uuid.UUID,
        resolution_hash: str,
        resolution: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ProviderMirrorConflict:
        await self._require_authorized()
        if resolution not in {"keep_atlas", "accept_provider", "merged"}:
            raise ProviderMirrorError("conflict resolution is invalid")
        if len(resolution_hash) != 64:
            raise ProviderMirrorError("resolution hash is invalid")
        key = self._key(idempotency_key)
        digest = self._digest(
            {
                "conflict_id": str(conflict_id),
                "resolution_hash": resolution_hash,
                "resolution": resolution,
            }
        )
        await self._repository.lock_idempotency(f"resolution:{key}")
        conflict = await self._repository.conflict(conflict_id, for_update=True)
        if conflict is None:
            raise ProviderMirrorError("mirror conflict is unavailable")
        if conflict.status == "resolved":
            if (
                conflict.resolution_idempotency_key == key
                and conflict.resolution_request_digest == digest
            ):
                return conflict
            raise ProviderMirrorReplayError("conflict resolution replay is invalid")
        mirror = await self._require_mirror(conflict.mirror_id, for_update=True)
        changed_at = now or datetime.now(UTC)
        conflict.status = "resolved"
        conflict.resolution = resolution
        conflict.resolution_hash = resolution_hash
        conflict.resolution_idempotency_key = key
        conflict.resolution_request_digest = digest
        conflict.resolved_by_user_id = self._context.actor.actor_id
        conflict.resolved_at = changed_at
        conflict.version += 1
        mirror.normalized_hash = resolution_hash
        mirror.authority = AuthorityPolicy.USER_RESOLVED.value
        mirror.sync_state = MirrorState.SYNCED.value
        mirror.version += 1
        mirror.updated_at = changed_at
        await self._record_event(mirror, "provider_mirror.conflict_resolved")
        return conflict

    def _apply_observation(
        self,
        mirror: ProviderMirror,
        observation: ProviderObservation,
        changed_at: datetime,
    ) -> None:
        mirror.provider_version = observation.provider_version
        mirror.etag = observation.etag
        mirror.provider_updated_at = observation.provider_updated_at
        mirror.normalized_hash = observation.normalized_hash
        mirror.raw_payload_reference = observation.raw_payload_reference
        mirror.raw_payload_owner = observation.raw_payload_owner
        mirror.sync_state = MirrorState.SYNCED.value
        mirror.version += 1
        mirror.updated_at = changed_at

    async def _ensure_conflict(
        self,
        mirror: ProviderMirror,
        *,
        reason: ConflictReason,
        provider_hash: str,
        provider_version: str,
        now: datetime,
        atlas_hash: str | None = None,
    ) -> ProviderMirrorConflict:
        existing = await self._repository.open_conflict(mirror.id)
        if existing is not None:
            return existing
        return await self._repository.add_conflict(
            ProviderMirrorConflict(
                workspace_id=mirror.workspace_id,
                id=uuid.uuid4(),
                mirror_id=mirror.id,
                reason=reason.value,
                atlas_hash=atlas_hash or mirror.normalized_hash,
                provider_hash=provider_hash,
                provider_version=provider_version,
                status="open",
                detected_at=now,
                version=1,
            )
        )

    async def _record_comparison(
        self,
        mirror: ProviderMirror,
        *,
        direction: ComparisonDirection,
        idempotency_key: str,
        request_digest: str,
        decision: ComparisonDecision,
        observation: ProviderObservation,
        conflict_reason: ConflictReason | None,
        now: datetime,
    ) -> ProviderMirrorComparison:
        return await self._repository.add_comparison(
            ProviderMirrorComparison(
                workspace_id=mirror.workspace_id,
                id=uuid.uuid4(),
                mirror_id=mirror.id,
                direction=direction.value,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                decision=decision.value,
                conflict_reason=(
                    conflict_reason.value if conflict_reason is not None else None
                ),
                observed_provider_version=observation.provider_version,
                observed_hash=observation.normalized_hash,
                mirror_version=mirror.version,
                created_at=now,
            )
        )

    async def _replayed_mirror(
        self,
        comparison: ProviderMirrorComparison,
        request_digest: str,
    ) -> ProviderMirror:
        if comparison.request_digest != request_digest:
            raise ProviderMirrorReplayError(
                "mirror idempotency key was reused with changed input"
            )
        return await self._require_mirror(comparison.mirror_id)

    async def _require_mirror(
        self, mirror_id: uuid.UUID, *, for_update: bool = False
    ) -> ProviderMirror:
        mirror = await self._repository.mirror(mirror_id, for_update=for_update)
        if mirror is None or mirror.sync_state == MirrorState.DELETED.value:
            raise ProviderMirrorError("provider mirror is unavailable")
        return mirror

    async def _require_authorized(self) -> None:
        if not await self._authorizer.authorize(
            self._context, "manage_workspace"
        ):
            raise ProviderMirrorAuthorizationError(
                "provider mirror administration is denied"
            )

    @staticmethod
    def _key(value: str) -> str:
        key = value.strip()
        if not key or len(key) > 128:
            raise ProviderMirrorError("mirror idempotency key is invalid")
        return key

    @staticmethod
    def _observation_payload(observation: ProviderObservation) -> dict[str, object]:
        return {
            "provider_version": observation.provider_version,
            "etag": observation.etag,
            "provider_updated_at": observation.provider_updated_at.isoformat(),
            "normalized_hash": observation.normalized_hash,
            "deleted": observation.deleted,
            "raw_payload_reference": observation.raw_payload_reference,
            "raw_payload_owner": observation.raw_payload_owner,
        }

    @staticmethod
    def _digest(payload: dict[str, object]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _record_event(self, mirror: ProviderMirror, action: str) -> None:
        details = {
            "mirror_id": str(mirror.id),
            "connection_id": str(mirror.connection_id),
            "resource_type": mirror.resource_type,
            "sync_state": mirror.sync_state,
            "version": mirror.version,
        }
        audit = await self._audit.write(
            AuditInput(
                action=action,
                target_type="provider_mirror",
                target_id=mirror.id,
                outcome="success",
                details=details,
                classification="internal",
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=mirror.workspace_id,
                id=uuid.uuid4(),
                event_type=action,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="provider_mirror",
                aggregate_id=mirror.id,
                aggregate_sequence=mirror.version,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="internal",
                payload={"audit_event_id": str(audit.id), **details},
            )
        )
        await self._session.flush()
