"""Provider-neutral H2-04 mirror authority and comparison contracts."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderMirrorError(ValueError):
    """A mirror observation or decision violates an H2-04 invariant."""


class ProviderMirrorAuthorizationError(ProviderMirrorError):
    """The current actor may not administer provider mirrors."""


class ProviderMirrorReplayError(ProviderMirrorError):
    """An idempotency key was reused for changed mirror input."""


class AuthorityPolicy(StrEnum):
    PROVIDER_AUTHORITATIVE = "provider_authoritative"
    ATLAS_AUTHORITATIVE = "atlas_authoritative"
    USER_RESOLVED = "user_resolved"
    MERGEABLE = "mergeable"


class MirrorState(StrEnum):
    SYNCED = "synced"
    CONFLICT = "conflict"
    TOMBSTONED = "tombstoned"
    DELETED = "deleted"


class ConflictReason(StrEnum):
    AMBIGUOUS_INBOUND = "ambiguous_inbound"
    PROVIDER_VERSION_REUSED = "provider_version_reused"
    PRECONDITION_FAILED = "precondition_failed"
    POST_WRITE_VERIFICATION_FAILED = "post_write_verification_failed"


class ComparisonDecision(StrEnum):
    APPLY = "apply"
    NO_CHANGE = "no_change"
    CONFLICT = "conflict"
    TOMBSTONE = "tombstone"
    PERMIT = "permit"
    DENY = "deny"
    REFRESH_REQUIRED = "refresh_required"


class ComparisonDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass(frozen=True, slots=True)
class MirrorCreate:
    mirror_id: uuid.UUID
    external_reference_id: uuid.UUID
    connection_id: uuid.UUID
    resource_type: str
    external_id: str
    authority: AuthorityPolicy
    field_authority: dict[str, AuthorityPolicy]
    observation: ProviderObservation

    def validated(self) -> MirrorCreate:
        resource_type = normalized_identifier(
            self.resource_type, field="resource type"
        )
        external_id = self.external_id.strip()
        if not external_id or len(external_id) > 1024:
            raise ProviderMirrorError("external ID is invalid")
        field_authority = {
            normalized_identifier(key, field="field authority key"): value
            for key, value in sorted(self.field_authority.items())
        }
        return replace(
            self,
            resource_type=resource_type,
            external_id=external_id,
            field_authority=field_authority,
            observation=self.observation.validated(),
        )


def normalized_identifier(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ProviderMirrorError(f"{field} must be a stable lowercase identifier")
    return normalized


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    provider_version: str
    etag: str | None
    provider_updated_at: datetime
    normalized_hash: str
    deleted: bool
    raw_payload_reference: str | None = None
    raw_payload_owner: str | None = None

    def validated(self) -> ProviderObservation:
        version = self.provider_version.strip()
        if not version or len(version) > 512:
            raise ProviderMirrorError("provider version is invalid")
        normalized_hash = self.normalized_hash.strip().lower()
        if not self.deleted and not _SHA256.fullmatch(normalized_hash):
            raise ProviderMirrorError("normalized hash must be SHA-256")
        if self.deleted and normalized_hash and not _SHA256.fullmatch(normalized_hash):
            raise ProviderMirrorError("normalized hash must be empty or SHA-256")
        if bool(self.raw_payload_reference) != bool(self.raw_payload_owner):
            raise ProviderMirrorError(
                "raw payload reference and approved owner must be paired"
            )
        owner = (
            normalized_identifier(self.raw_payload_owner, field="raw payload owner")
            if self.raw_payload_owner
            else None
        )
        return replace(
            self,
            provider_version=version,
            normalized_hash=normalized_hash,
            raw_payload_owner=owner,
        )


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    decision: ComparisonDecision
    conflict_reason: ConflictReason | None = None


def decide_inbound(
    *,
    authority: AuthorityPolicy,
    current_version: str,
    current_hash: str,
    observation: ProviderObservation,
) -> ComparisonResult:
    observation = observation.validated()
    if observation.deleted:
        return ComparisonResult(ComparisonDecision.TOMBSTONE)
    if (
        observation.provider_version == current_version
        and observation.normalized_hash == current_hash
    ):
        return ComparisonResult(ComparisonDecision.NO_CHANGE)
    if observation.provider_version == current_version:
        return ComparisonResult(
            ComparisonDecision.CONFLICT,
            ConflictReason.PROVIDER_VERSION_REUSED,
        )
    if authority is AuthorityPolicy.PROVIDER_AUTHORITATIVE:
        return ComparisonResult(ComparisonDecision.APPLY)
    return ComparisonResult(
        ComparisonDecision.CONFLICT,
        ConflictReason.AMBIGUOUS_INBOUND,
    )


def decide_outbound(
    *,
    authority: AuthorityPolicy,
    current_version: str,
    expected_version: str,
) -> ComparisonResult:
    if authority is AuthorityPolicy.PROVIDER_AUTHORITATIVE:
        return ComparisonResult(ComparisonDecision.DENY)
    if expected_version != current_version:
        return ComparisonResult(
            ComparisonDecision.REFRESH_REQUIRED,
            ConflictReason.PRECONDITION_FAILED,
        )
    return ComparisonResult(ComparisonDecision.PERMIT)
