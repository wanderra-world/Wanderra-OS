"""Failing-first H3-04 domain contract tests."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.documents import Classification
from app.knowledge.contracts import (
    ClaimCreate,
    ClaimEvidence,
    ClaimValueType,
    KnowledgeError,
    TimelineInput,
    canonical_claim_digest,
    checkpoint_digest,
    effective_classification,
    rebuild_timeline,
)
from app.knowledge.jobs import DurableSourceDispositionJobAdapter

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


def test_typed_claim_identity_is_canonical_and_changed_input_is_distinct() -> None:
    subject = uuid4()
    first = ClaimCreate(
        claim_id=uuid4(),
        subject_resource_id=subject,
        predicate="company.registration_number",
        value_type=ClaimValueType.TEXT,
        value="  SE-123  ",
        confidence=0.9,
        extractor_key="atlas.claims",
        extractor_version="1",
        classification=Classification.CONFIDENTIAL,
        policy_version=2,
    )
    assert first.canonical_value == "SE-123"
    assert first.identity_digest == canonical_claim_digest(
        subject_resource_id=subject,
        predicate="company.registration_number",
        value_type=ClaimValueType.TEXT,
        canonical_value="SE-123",
    )
    changed = ClaimCreate(
        claim_id=uuid4(),
        subject_resource_id=subject,
        predicate="company.registration_number",
        value_type=ClaimValueType.TEXT,
        value="SE-124",
        confidence=0.9,
        extractor_key="atlas.claims",
        extractor_version="1",
        classification=Classification.CONFIDENTIAL,
        policy_version=2,
    )
    assert changed.identity_digest != first.identity_digest


def test_claim_types_confidence_and_validity_fail_closed() -> None:
    with pytest.raises(KnowledgeError):
        ClaimCreate(
            claim_id=uuid4(),
            subject_resource_id=uuid4(),
            predicate="company.active",
            value_type=ClaimValueType.BOOLEAN,
            value="yes",
            confidence=1.1,
            extractor_key="atlas.claims",
            extractor_version="1",
            classification=Classification.INTERNAL,
            policy_version=1,
            valid_from=NOW,
            valid_to=NOW,
        )


def test_source_span_is_bounded_and_hash_linked() -> None:
    evidence = ClaimEvidence(
        evidence_id=uuid4(),
        source_version_id=uuid4(),
        source_chunk_id=uuid4(),
        source_hash="a" * 64,
        span_start=3,
        span_end=9,
        classification=Classification.CONFIDENTIAL,
        policy_version=2,
    )
    assert evidence.span_end > evidence.span_start
    with pytest.raises(KnowledgeError, match="span"):
        ClaimEvidence(
            evidence_id=uuid4(),
            source_version_id=uuid4(),
            source_chunk_id=None,
            source_hash="a" * 64,
            span_start=9,
            span_end=3,
            classification=Classification.INTERNAL,
            policy_version=1,
        )


def test_claim_derivation_replay_detects_changed_source_input() -> None:
    command = ClaimCreate(
        claim_id=uuid4(),
        subject_resource_id=uuid4(),
        predicate="company.location",
        value_type=ClaimValueType.TEXT,
        value="Stockholm",
        confidence=0.9,
        extractor_key="atlas.claims",
        extractor_version="1",
        classification=Classification.CONFIDENTIAL,
        policy_version=1,
    )
    source_version_id = uuid4()
    first = ClaimEvidence(
        evidence_id=uuid4(),
        source_version_id=source_version_id,
        source_chunk_id=None,
        source_hash="a" * 64,
        span_start=0,
        span_end=5,
        classification=Classification.CONFIDENTIAL,
        policy_version=1,
    )
    changed = ClaimEvidence(
        evidence_id=uuid4(),
        source_version_id=source_version_id,
        source_chunk_id=None,
        source_hash="a" * 64,
        span_start=0,
        span_end=6,
        classification=Classification.CONFIDENTIAL,
        policy_version=1,
    )
    assert command.derivation_digest((first,)) != command.derivation_digest((changed,))


def test_derivative_classification_uses_most_restrictive_source() -> None:
    assert (
        effective_classification((Classification.INTERNAL, Classification.RESTRICTED))
        is Classification.RESTRICTED
    )
    with pytest.raises(KnowledgeError):
        effective_classification(())


def test_timeline_rebuild_is_ordered_deterministic_and_idempotent() -> None:
    ids = (
        UUID("00000000-0000-0000-0000-000000000002"),
        UUID("00000000-0000-0000-0000-000000000001"),
    )
    values = tuple(
        TimelineInput(
            source_event_id=event_id,
            source_event_type="knowledge.claim.created",
            source_sequence=1,
            occurred_at=NOW,
            resource_id=uuid4(),
            source_claim_id=None,
            title=f"event-{event_id}",
            visibility="workspace",
            classification=Classification.INTERNAL,
            policy_version=1,
        )
        for event_id in ids
    )
    first = rebuild_timeline(values)
    assert tuple(item.source_event_id for item in first) == tuple(reversed(ids))
    assert rebuild_timeline(values + values) == first
    assert checkpoint_digest(first) == checkpoint_digest(reversed(first))


def test_timeline_rejects_audit_as_projection_storage() -> None:
    with pytest.raises(KnowledgeError, match="audit"):
        TimelineInput(
            source_event_id=uuid4(),
            source_event_type="audit.event",
            source_sequence=1,
            occurred_at=NOW,
            resource_id=uuid4(),
            source_claim_id=None,
            title="audit copy",
            visibility="workspace",
            classification=Classification.INTERNAL,
            policy_version=1,
        )


async def test_source_disposition_uses_typed_h3_02_idempotent_envelope() -> None:
    class Jobs:
        def __init__(self) -> None:
            self.command = None

        async def enqueue(self, command, *, now):
            self.command = command
            return type("Job", (), {"id": command.job_id})()

    jobs = Jobs()
    source_version_id = uuid4()
    adapter = DurableSourceDispositionJobAdapter(
        jobs,
        definition_id=uuid4(),
        id_factory=lambda: UUID("00000000-0000-0000-0000-000000000004"),
        clock=lambda: NOW,
    )
    assert await adapter.enqueue_source_disposition(source_version_id) == UUID(
        "00000000-0000-0000-0000-000000000004"
    )
    assert jobs.command.command_type == "knowledge.source_disposition"
    assert jobs.command.payload == {"source_version_id": str(source_version_id)}
    assert jobs.command.idempotency_key == f"knowledge-source-disposition:{source_version_id}"
