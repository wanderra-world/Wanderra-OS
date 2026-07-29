"""Derivative-lineage deletion simulation for the H0-09 prototype."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tests.architecture.lineage_deletion_prototype import (
    Artifact,
    ArtifactKind,
    ArtifactState,
    BackupDisposition,
    ErasureRequest,
    ErasureWorkflow,
    Governance,
    LineageError,
    LineageGraph,
    MockProviderDeletion,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def artifact(
    workspace_id: UUID,
    kind: ArtifactKind,
    *,
    sources: tuple[UUID, ...] = (),
    governance: Governance | None = None,
) -> Artifact:
    return Artifact(
        id=uuid4(),
        workspace_id=workspace_id,
        kind=kind,
        direct_sources=sources,
        derivation_type="derived" if sources else None,
        tool_or_model_version="atlas-test-1" if sources else None,
        created_at=NOW,
        policy_version="policy-1",
        classification_version="classification-1",
        content_hash="content-hash",
        governance=governance or Governance(),
    )


def representative_graph(
    *,
    provider_governance: Governance | None = None,
    backup_disposition: BackupDisposition = BackupDisposition.KEY_ERASURE,
) -> tuple[LineageGraph, UUID, dict[ArtifactKind, UUID]]:
    workspace_id = uuid4()
    graph = LineageGraph()
    root = artifact(
        workspace_id,
        ArtifactKind.PROVIDER_MIRROR,
        governance=provider_governance,
    )
    graph.add(root)
    raw = artifact(workspace_id, ArtifactKind.RAW_PAYLOAD, sources=(root.id,))
    document = artifact(
        workspace_id,
        ArtifactKind.DOCUMENT_VERSION,
        sources=(raw.id,),
    )
    graph.add(raw)
    graph.add(document)

    by_kind: dict[ArtifactKind, UUID] = {
        root.kind: root.id,
        raw.kind: raw.id,
        document.kind: document.id,
    }
    parent = document
    for kind in (
        ArtifactKind.DOCUMENT_CHUNK,
        ArtifactKind.EXTRACTED_CLAIM,
        ArtifactKind.TIMELINE_PROJECTION,
        ArtifactKind.SEARCH_PROJECTION,
        ArtifactKind.EMBEDDING,
        ArtifactKind.MEMORY,
        ArtifactKind.NOTE,
        ArtifactKind.CACHE,
        ArtifactKind.EXPORT,
    ):
        derivative = artifact(workspace_id, kind, sources=(parent.id,))
        graph.add(derivative)
        by_kind[kind] = derivative.id
        parent = derivative
    backup = artifact(
        workspace_id,
        ArtifactKind.BACKUP,
        sources=(parent.id,),
        governance=Governance(backup_disposition=backup_disposition),
    )
    graph.add(backup)
    by_kind[ArtifactKind.BACKUP] = backup.id
    return graph, workspace_id, by_kind


def request(workspace_id: UUID, root_id: UUID, *, key: str = "erase-001"):
    return ErasureRequest(
        workspace_id=workspace_id,
        root_artifact_id=root_id,
        idempotency_key=key,
    )


def test_fit_lineage_001_derivatives_require_complete_provenance() -> None:
    """FIT-LINEAGE-001 requires traceable derivation metadata."""

    with pytest.raises(LineageError, match="derivatives require"):
        Artifact(
            id=uuid4(),
            workspace_id=uuid4(),
            kind=ArtifactKind.EMBEDDING,
            direct_sources=(uuid4(),),
            derivation_type=None,
            tool_or_model_version=None,
            created_at=NOW,
            policy_version="policy-1",
            classification_version="classification-1",
            content_hash="hash",
            governance=Governance(),
        )


def test_fit_lineage_002_cross_workspace_lineage_is_rejected() -> None:
    """FIT-LINEAGE-002 prevents derivative edges across workspace boundaries."""

    graph = LineageGraph()
    source = artifact(uuid4(), ArtifactKind.DOCUMENT_VERSION)
    graph.add(source)

    with pytest.raises(LineageError, match="cross-workspace"):
        graph.add(
            artifact(
                uuid4(),
                ArtifactKind.DOCUMENT_CHUNK,
                sources=(source.id,),
            )
        )


def test_fit_lineage_003_erasure_traverses_all_derivatives() -> None:
    """FIT-LINEAGE-003 deletes every eligible source and transitive derivative."""

    graph, workspace_id, by_kind = representative_graph()
    workflow = ErasureWorkflow(graph, MockProviderDeletion())
    receipt = workflow.execute(
        request(workspace_id, by_kind[ArtifactKind.PROVIDER_MIRROR]),
        now=NOW,
    )

    assert set(receipt.deleted_ids) == set(by_kind.values())
    assert receipt.retained == ()
    assert len(receipt.verification_hash) == 64
    assert all(
        graph.get(artifact_id).state is ArtifactState.DELETED
        for artifact_id in by_kind.values()
    )


@pytest.mark.parametrize(
    ("governance", "reason"),
    [
        (Governance(legal_hold=True), "legal_hold"),
        (
            Governance(statutory_retain_until=NOW + timedelta(days=30)),
            "statutory_or_contractual_minimum",
        ),
        (
            Governance(
                security_preserve_until=NOW + timedelta(days=10),
                security_preservation_approved=True,
            ),
            "approved_security_preservation",
        ),
        (
            Governance(workspace_retain_until=NOW + timedelta(days=5)),
            "workspace_policy",
        ),
    ],
)
def test_fit_lineage_004_policy_precedence_retains_governed_artifact(
    governance: Governance,
    reason: str,
) -> None:
    """FIT-LINEAGE-004 applies higher-priority retention before user deletion."""

    workspace_id = uuid4()
    graph = LineageGraph()
    root = artifact(
        workspace_id,
        ArtifactKind.DOCUMENT_VERSION,
        governance=governance,
    )
    graph.add(root)
    receipt = ErasureWorkflow(graph, MockProviderDeletion()).execute(
        request(workspace_id, root.id),
        now=NOW,
    )

    assert receipt.retained[0].reason == reason
    assert graph.get(root.id).state is ArtifactState.RETAINED
    with pytest.raises(LineageError, match="unavailable"):
        graph.read(root.id)


def test_fit_lineage_005_tombstoned_source_cannot_create_derivatives() -> None:
    """FIT-LINEAGE-005 stops ordinary access and new derivation immediately."""

    workspace_id = uuid4()
    graph = LineageGraph()
    root = artifact(
        workspace_id,
        ArtifactKind.DOCUMENT_VERSION,
        governance=Governance(legal_hold=True),
    )
    graph.add(root)
    ErasureWorkflow(graph, MockProviderDeletion()).execute(
        request(workspace_id, root.id),
        now=NOW,
    )

    with pytest.raises(LineageError, match="cannot produce"):
        graph.add(
            artifact(
                workspace_id,
                ArtifactKind.DOCUMENT_CHUNK,
                sources=(root.id,),
            )
        )


def test_fit_lineage_006_search_embedding_timeline_and_cache_are_invalidated() -> None:
    """FIT-LINEAGE-006 explicitly reports invalidated retrieval projections."""

    graph, workspace_id, by_kind = representative_graph()
    receipt = ErasureWorkflow(graph, MockProviderDeletion()).execute(
        request(workspace_id, by_kind[ArtifactKind.PROVIDER_MIRROR]),
        now=NOW,
    )

    expected = {
        by_kind[ArtifactKind.TIMELINE_PROJECTION],
        by_kind[ArtifactKind.SEARCH_PROJECTION],
        by_kind[ArtifactKind.EMBEDDING],
        by_kind[ArtifactKind.CACHE],
    }
    assert set(receipt.invalidated_projection_ids) == expected


def test_fit_lineage_007_provider_action_is_invoked_only_when_policy_requires() -> None:
    """FIT-LINEAGE-007 limits and verifies external deletion side effects."""

    provider = MockProviderDeletion()
    graph, workspace_id, by_kind = representative_graph(
        provider_governance=Governance(provider_delete_required=True)
    )
    receipt = ErasureWorkflow(graph, provider).execute(
        request(workspace_id, by_kind[ArtifactKind.PROVIDER_MIRROR]),
        now=NOW,
    )

    provider_id = by_kind[ArtifactKind.PROVIDER_MIRROR]
    assert provider.calls == [provider_id]
    assert receipt.verified_provider_ids == (provider_id,)


def test_fit_lineage_008_unverified_provider_action_is_reported_not_hidden() -> None:
    """FIT-LINEAGE-008 retains evidence when provider verification fails."""

    provider = MockProviderDeletion(verification_succeeds=False)
    graph, workspace_id, by_kind = representative_graph(
        provider_governance=Governance(provider_delete_required=True)
    )
    provider_id = by_kind[ArtifactKind.PROVIDER_MIRROR]
    receipt = ErasureWorkflow(graph, provider).execute(
        request(workspace_id, provider_id),
        now=NOW,
    )

    assert graph.get(provider_id).state is ArtifactState.RETAINED
    assert any(
        exception.artifact_id == provider_id
        and exception.reason == "provider_action_unverified"
        for exception in receipt.retained
    )


@pytest.mark.parametrize(
    ("disposition", "expected_state", "reason"),
    [
        (BackupDisposition.KEY_ERASURE, ArtifactState.DELETED, None),
        (
            BackupDisposition.SCHEDULED_EXPIRY,
            ArtifactState.RETAINED,
            "backup_scheduled_expiry",
        ),
    ],
)
def test_fit_lineage_009_backup_deletion_uses_governed_disposition(
    disposition: BackupDisposition,
    expected_state: ArtifactState,
    reason: str | None,
) -> None:
    """FIT-LINEAGE-009 makes backups expire or inaccessible through key erasure."""

    graph, workspace_id, by_kind = representative_graph(
        backup_disposition=disposition
    )
    receipt = ErasureWorkflow(graph, MockProviderDeletion()).execute(
        request(workspace_id, by_kind[ArtifactKind.PROVIDER_MIRROR]),
        now=NOW,
    )
    backup_id = by_kind[ArtifactKind.BACKUP]

    assert graph.get(backup_id).state is expected_state
    if reason is not None:
        assert any(exception.reason == reason for exception in receipt.retained)
        assert receipt.backup_expiry_ids == (backup_id,)


def test_fit_lineage_010_exact_retry_returns_original_receipt() -> None:
    """FIT-LINEAGE-010 makes erasure idempotent without duplicate audit evidence."""

    graph, workspace_id, by_kind = representative_graph()
    workflow = ErasureWorkflow(graph, MockProviderDeletion())
    erasure_request = request(
        workspace_id,
        by_kind[ArtifactKind.PROVIDER_MIRROR],
    )

    first = workflow.execute(erasure_request, now=NOW)
    second = workflow.execute(erasure_request, now=NOW + timedelta(hours=1))

    assert second == first
    assert len(workflow.audit_evidence) == 1


def test_fit_lineage_011_changed_idempotency_scope_is_rejected() -> None:
    """FIT-LINEAGE-011 prevents a prior key from authorizing different deletion."""

    graph, workspace_id, by_kind = representative_graph()
    workflow = ErasureWorkflow(graph, MockProviderDeletion())
    workflow.execute(
        request(workspace_id, by_kind[ArtifactKind.PROVIDER_MIRROR]),
        now=NOW,
    )

    with pytest.raises(LineageError, match="changed scope"):
        workflow.execute(
            request(workspace_id, uuid4()),
            now=NOW,
        )


def test_fit_lineage_012_minimal_audit_excludes_source_content() -> None:
    """FIT-LINEAGE-012 retains accountability evidence without deleted payloads."""

    graph, workspace_id, by_kind = representative_graph()
    workflow = ErasureWorkflow(graph, MockProviderDeletion())
    receipt = workflow.execute(
        request(workspace_id, by_kind[ArtifactKind.PROVIDER_MIRROR]),
        now=NOW,
    )

    audit = workflow.audit_evidence[0]
    assert audit.receipt_id == receipt.receipt_id
    assert not hasattr(audit, "content")
    assert not hasattr(audit, "raw_payload")
