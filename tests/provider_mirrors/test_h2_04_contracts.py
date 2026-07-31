"""Failing-first contract tests for the H2-04 mirror boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.provider_mirrors import (
    AuthorityPolicy,
    ComparisonDecision,
    ConflictReason,
    MirrorState,
    ProviderMirrorError,
    ProviderObservation,
    decide_inbound,
    decide_outbound,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
HASH_1 = "1" * 64
HASH_2 = "2" * 64


def observation(
    *,
    version: str = "v1",
    normalized_hash: str = HASH_1,
    deleted: bool = False,
) -> ProviderObservation:
    return ProviderObservation(
        provider_version=version,
        etag='"etag-v1"',
        provider_updated_at=NOW,
        normalized_hash=normalized_hash,
        deleted=deleted,
    )


def test_observation_is_provider_neutral_and_validated() -> None:
    assert observation().validated().normalized_hash == HASH_1
    with pytest.raises(ProviderMirrorError, match="hash"):
        observation(normalized_hash="not-a-sha256").validated()
    with pytest.raises(ProviderMirrorError, match="paired"):
        ProviderObservation(
            provider_version="v1",
            etag=None,
            provider_updated_at=NOW,
            normalized_hash=HASH_1,
            deleted=False,
            raw_payload_reference="object/one",
        ).validated()


@pytest.mark.parametrize(
    ("authority", "decision"),
    [
        (AuthorityPolicy.PROVIDER_AUTHORITATIVE, ComparisonDecision.APPLY),
        (AuthorityPolicy.ATLAS_AUTHORITATIVE, ComparisonDecision.CONFLICT),
        (AuthorityPolicy.USER_RESOLVED, ComparisonDecision.CONFLICT),
        (AuthorityPolicy.MERGEABLE, ComparisonDecision.CONFLICT),
    ],
)
def test_inbound_authority_decision_table(
    authority: AuthorityPolicy,
    decision: ComparisonDecision,
) -> None:
    result = decide_inbound(
        authority=authority,
        current_version="v1",
        current_hash=HASH_1,
        observation=observation(version="v2", normalized_hash=HASH_2),
    )
    assert result.decision is decision
    if decision is ComparisonDecision.CONFLICT:
        assert result.conflict_reason is ConflictReason.AMBIGUOUS_INBOUND


def test_replay_version_reuse_and_tombstone_are_deterministic() -> None:
    unchanged = decide_inbound(
        authority=AuthorityPolicy.PROVIDER_AUTHORITATIVE,
        current_version="v1",
        current_hash=HASH_1,
        observation=observation(),
    )
    assert unchanged.decision is ComparisonDecision.NO_CHANGE

    reused = decide_inbound(
        authority=AuthorityPolicy.PROVIDER_AUTHORITATIVE,
        current_version="v1",
        current_hash=HASH_1,
        observation=observation(normalized_hash=HASH_2),
    )
    assert reused.conflict_reason is ConflictReason.PROVIDER_VERSION_REUSED

    tombstone = decide_inbound(
        authority=AuthorityPolicy.ATLAS_AUTHORITATIVE,
        current_version="v1",
        current_hash=HASH_1,
        observation=observation(version="v2", deleted=True),
    )
    assert tombstone.decision is ComparisonDecision.TOMBSTONE


def test_outbound_precondition_never_blindly_retries() -> None:
    permitted = decide_outbound(
        authority=AuthorityPolicy.ATLAS_AUTHORITATIVE,
        current_version="v2",
        expected_version="v2",
    )
    assert permitted.decision is ComparisonDecision.PERMIT

    stale = decide_outbound(
        authority=AuthorityPolicy.ATLAS_AUTHORITATIVE,
        current_version="v2",
        expected_version="v1",
    )
    assert stale.decision is ComparisonDecision.REFRESH_REQUIRED
    assert stale.conflict_reason is ConflictReason.PRECONDITION_FAILED

    denied = decide_outbound(
        authority=AuthorityPolicy.PROVIDER_AUTHORITATIVE,
        current_version="v2",
        expected_version="v2",
    )
    assert denied.decision is ComparisonDecision.DENY


def test_provider_tombstone_is_not_atlas_deletion() -> None:
    assert MirrorState.TOMBSTONED != MirrorState.DELETED
