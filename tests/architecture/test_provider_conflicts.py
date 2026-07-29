"""Provider authority and conflict matrix for the H0-08 prototype."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.architecture.provider_mirror_prototype import (
    AuthorityPolicy,
    ConflictReason,
    MockGoogleProvider,
    ProviderMirrorError,
    ProviderMirrorService,
    ProviderMirrorStore,
    ProviderSnapshot,
    SyncState,
    new_mirror,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def snapshot(
    *,
    version: str = "1",
    normalized_hash: str = "provider-v1",
    deleted: bool = False,
) -> ProviderSnapshot:
    return ProviderSnapshot(
        external_id="google-file-001",
        version=version,
        normalized_hash=normalized_hash,
        updated_at=NOW,
        raw_payload_reference=f"raw/google-file-001/{version}",
        deleted=deleted,
    )


def setup_service(
    authority: AuthorityPolicy,
) -> tuple[ProviderMirrorStore, MockGoogleProvider, ProviderMirrorService]:
    initial = snapshot()
    store = ProviderMirrorStore()
    store.add(new_mirror(initial, authority=authority))
    provider = MockGoogleProvider((initial,))
    return store, provider, ProviderMirrorService(store, provider)


def only_mirror(store: ProviderMirrorStore):
    return store.all()[0]


def test_fit_mirror_001_unique_provider_key_is_enforced() -> None:
    """FIT-MIRROR-001 prevents duplicate external-resource ownership."""

    initial = snapshot()
    workspace_id = uuid4()
    connection_id = uuid4()
    first = new_mirror(
        initial,
        authority=AuthorityPolicy.PROVIDER_AUTHORITATIVE,
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    duplicate = replace(first, id=uuid4())
    store = ProviderMirrorStore()
    store.add(first)

    with pytest.raises(ProviderMirrorError, match="unique key"):
        store.add(duplicate)


def test_fit_mirror_002_provider_resources_require_approved_promotion() -> None:
    """FIT-MIRROR-002 keeps provider records as mirrors until approved."""

    store, _, service = setup_service(AuthorityPolicy.PROVIDER_AUTHORITATIVE)
    mirror = only_mirror(store)
    assert mirror.canonical_reference is None

    with pytest.raises(ProviderMirrorError, match="approved command"):
        service.promote(mirror.id, canonical_reference=uuid4(), approved=False)

    canonical_id = uuid4()
    promoted = service.promote(
        mirror.id,
        canonical_reference=canonical_id,
        approved=True,
    )
    assert promoted.canonical_reference == canonical_id


def test_fit_mirror_003_provider_authoritative_inbound_update_applies() -> None:
    """FIT-MIRROR-003 accepts a newer provider-authoritative version."""

    store, _, service = setup_service(AuthorityPolicy.PROVIDER_AUTHORITATIVE)
    mirror = only_mirror(store)
    updated = service.apply_inbound(
        mirror.id,
        snapshot(version="2", normalized_hash="provider-v2"),
        now=NOW + timedelta(minutes=1),
    )

    assert updated.sync_state is SyncState.SYNCED
    assert updated.provider_version == "2"
    assert updated.normalized_hash == "provider-v2"


@pytest.mark.parametrize(
    "authority",
    [AuthorityPolicy.ATLAS_AUTHORITATIVE, AuthorityPolicy.USER_RESOLVED],
)
def test_fit_mirror_004_ambiguous_inbound_change_enters_conflict(
    authority: AuthorityPolicy,
) -> None:
    """FIT-MIRROR-004 prohibits destructive last-write-wins."""

    store, _, service = setup_service(authority)
    mirror = only_mirror(store)
    conflicted = service.apply_inbound(
        mirror.id,
        snapshot(version="2", normalized_hash="provider-v2"),
        now=NOW + timedelta(minutes=1),
    )

    assert conflicted.sync_state is SyncState.CONFLICT
    assert conflicted.normalized_hash == "provider-v1"
    assert conflicted.conflict is not None
    assert conflicted.conflict.reason is ConflictReason.AMBIGUOUS_INBOUND
    assert conflicted.conflict.provider_hash == "provider-v2"


def test_fit_mirror_005_mergeable_change_requires_explicit_merge_result() -> None:
    """FIT-MIRROR-005 treats an absent merge result as ambiguity."""

    store, _, service = setup_service(AuthorityPolicy.MERGEABLE)
    mirror = only_mirror(store)
    inbound = snapshot(version="2", normalized_hash="provider-v2")

    conflicted = service.apply_inbound(mirror.id, inbound, now=NOW)
    assert conflicted.sync_state is SyncState.CONFLICT

    store, _, service = setup_service(AuthorityPolicy.MERGEABLE)
    mirror = only_mirror(store)
    merged = service.apply_inbound(
        mirror.id,
        inbound,
        now=NOW,
        merged_hash="deterministic-merge",
    )
    assert merged.sync_state is SyncState.SYNCED
    assert merged.normalized_hash == "deterministic-merge"


def test_fit_mirror_006_reused_provider_version_with_changed_content_conflicts() -> None:
    """FIT-MIRROR-006 rejects provider version ambiguity."""

    store, _, service = setup_service(AuthorityPolicy.PROVIDER_AUTHORITATIVE)
    mirror = only_mirror(store)
    conflicted = service.apply_inbound(
        mirror.id,
        snapshot(normalized_hash="changed-with-same-version"),
        now=NOW,
    )

    assert conflicted.sync_state is SyncState.CONFLICT
    assert conflicted.conflict is not None
    assert conflicted.conflict.reason is ConflictReason.PROVIDER_VERSION_REUSED


def test_fit_mirror_007_outbound_write_uses_precondition_and_verification() -> None:
    """FIT-MIRROR-007 updates only the expected version and verifies the result."""

    store, provider, service = setup_service(AuthorityPolicy.ATLAS_AUTHORITATIVE)
    mirror = only_mirror(store)
    updated = service.write_outbound(
        mirror.id,
        normalized_hash="atlas-v2",
        idempotency_key="command-001",
        now=NOW + timedelta(minutes=1),
    )

    assert updated.sync_state is SyncState.SYNCED
    assert updated.provider_version == "2"
    assert updated.normalized_hash == "atlas-v2"
    assert provider.update_calls == 1


def test_fit_mirror_008_failed_precondition_refreshes_without_retry() -> None:
    """FIT-MIRROR-008 refreshes and conflicts instead of blindly retrying."""

    store, provider, service = setup_service(AuthorityPolicy.ATLAS_AUTHORITATIVE)
    mirror = only_mirror(store)
    provider.simulate_external_change(
        snapshot(
            version="2",
            normalized_hash="concurrent-provider-v2",
        )
    )

    conflicted = service.write_outbound(
        mirror.id,
        normalized_hash="atlas-v2",
        idempotency_key="command-002",
        now=NOW,
    )

    assert provider.update_calls == 0
    assert conflicted.sync_state is SyncState.CONFLICT
    assert conflicted.provider_version == "2"
    assert conflicted.conflict is not None
    assert conflicted.conflict.reason is ConflictReason.PRECONDITION_FAILED


def test_fit_mirror_009_exact_idempotent_retry_has_one_external_effect() -> None:
    """FIT-MIRROR-009 returns an identical provider outcome for exact retries."""

    initial = snapshot()
    provider = MockGoogleProvider((initial,))
    first = provider.update(
        initial.external_id,
        normalized_hash="atlas-v2",
        expected_version="1",
        idempotency_key="stable-command",
        now=NOW,
    )
    second = provider.update(
        initial.external_id,
        normalized_hash="atlas-v2",
        expected_version="1",
        idempotency_key="stable-command",
        now=NOW,
    )

    assert second == first
    assert provider.update_calls == 1


def test_fit_mirror_010_changed_idempotent_retry_is_rejected() -> None:
    """FIT-MIRROR-010 prevents one key from authorizing changed input."""

    initial = snapshot()
    provider = MockGoogleProvider((initial,))
    provider.update(
        initial.external_id,
        normalized_hash="atlas-v2",
        expected_version="1",
        idempotency_key="stable-command",
        now=NOW,
    )

    with pytest.raises(ProviderMirrorError, match="changed input"):
        provider.update(
            initial.external_id,
            normalized_hash="different-atlas-value",
            expected_version="1",
            idempotency_key="stable-command",
            now=NOW,
        )


def test_fit_mirror_011_post_write_drift_enters_conflict() -> None:
    """FIT-MIRROR-011 detects provider divergence during write verification."""

    store, provider, service = setup_service(AuthorityPolicy.ATLAS_AUTHORITATIVE)
    provider.drift_after_write = True
    mirror = only_mirror(store)

    conflicted = service.write_outbound(
        mirror.id,
        normalized_hash="atlas-v2",
        idempotency_key="command-003",
        now=NOW,
    )

    assert conflicted.sync_state is SyncState.CONFLICT
    assert conflicted.conflict is not None
    assert conflicted.conflict.reason is ConflictReason.POST_WRITE_VERIFICATION_FAILED


def test_fit_mirror_012_provider_authority_rejects_outbound_write() -> None:
    """FIT-MIRROR-012 preserves explicit provider authority."""

    store, _, service = setup_service(AuthorityPolicy.PROVIDER_AUTHORITATIVE)

    with pytest.raises(ProviderMirrorError, match="rejects Atlas write"):
        service.write_outbound(
            only_mirror(store).id,
            normalized_hash="atlas-v2",
            idempotency_key="command-004",
            now=NOW,
        )


def test_fit_mirror_013_provider_deletion_tombstones_without_erasing_evidence() -> None:
    """FIT-MIRROR-013 separates provider deletion from governed Atlas erasure."""

    store, _, service = setup_service(AuthorityPolicy.PROVIDER_AUTHORITATIVE)
    mirror = only_mirror(store)
    canonical_id = uuid4()
    service.promote(mirror.id, canonical_reference=canonical_id, approved=True)

    tombstone = service.apply_inbound(
        mirror.id,
        snapshot(version="2", normalized_hash="", deleted=True),
        now=NOW,
    )

    assert tombstone.sync_state is SyncState.TOMBSTONED
    assert tombstone.tombstone
    assert tombstone.canonical_reference == canonical_id
    assert tombstone.raw_payload_reference


@pytest.mark.parametrize(
    ("authorized", "policy_allows", "verified"),
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ],
)
def test_fit_mirror_014_atlas_deletion_is_separately_governed(
    authorized: bool,
    policy_allows: bool,
    verified: bool,
) -> None:
    """FIT-MIRROR-014 requires policy-controlled, verified Atlas deletion."""

    store, _, service = setup_service(AuthorityPolicy.PROVIDER_AUTHORITATIVE)
    mirror = only_mirror(store)

    with pytest.raises(ProviderMirrorError, match="authorization, policy"):
        service.delete_atlas_evidence(
            mirror.id,
            authorized=authorized,
            policy_allows=policy_allows,
            provider_action_verified=verified,
        )


def test_fit_mirror_015_governed_atlas_deletion_can_complete() -> None:
    """FIT-MIRROR-015 completes only an authorized and verified deletion."""

    store, _, service = setup_service(AuthorityPolicy.PROVIDER_AUTHORITATIVE)
    mirror = only_mirror(store)
    service.promote(mirror.id, canonical_reference=uuid4(), approved=True)

    deleted = service.delete_atlas_evidence(
        mirror.id,
        authorized=True,
        policy_allows=True,
        provider_action_verified=True,
    )

    assert deleted.sync_state is SyncState.DELETED
    assert deleted.canonical_reference is None
