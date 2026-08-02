"""Failing-first domain tests for H3-03 documents and governed derivation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.documents.contracts import (
    Classification,
    CustodyError,
    DeletionDisposition,
    DocumentVersionCreate,
    MalwareVerdict,
    VerificationEvidence,
    build_chunks,
    deletion_disposition,
    derivative_digest,
    require_derivative_classification,
    require_extractable,
)
from app.documents.jobs import DurableDeletionJobAdapter, DurableExtractionJobAdapter

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


def test_document_version_is_content_addressed_and_rejects_hash_substitution() -> None:
    command = DocumentVersionCreate(
        version_id=uuid4(),
        document_id=uuid4(),
        content=b"canonical evidence",
        expected_sha256="01bae7a9f8b96d55c3e7fdb9a1b76fd9fd9c35cd82a47fd73b0d502d2d448a59",
        media_type="text/plain",
        classification=Classification.CONFIDENTIAL,
        classification_policy_version=3,
        encryption_key_version=2,
    )
    assert command.sha256 == command.expected_sha256
    assert command.size_bytes == 18
    with pytest.raises(CustodyError, match="hash"):
        DocumentVersionCreate(
            version_id=uuid4(),
            document_id=uuid4(),
            content=b"substituted",
            expected_sha256="0" * 64,
            media_type="text/plain",
            classification=Classification.INTERNAL,
            classification_policy_version=1,
            encryption_key_version=1,
        )


def test_only_verified_clean_content_is_extractable() -> None:
    require_extractable(
        VerificationEvidence(
            content_hash="a" * 64,
            malware_verdict=MalwareVerdict.CLEAN,
            media_type_verified=True,
            verified_at=NOW,
            verifier_version="scanner/1",
        ),
        expected_hash="a" * 64,
    )
    for evidence in (
        VerificationEvidence(
            content_hash="a" * 64,
            malware_verdict=MalwareVerdict.INFECTED,
            media_type_verified=True,
            verified_at=NOW,
            verifier_version="scanner/1",
        ),
        VerificationEvidence(
            content_hash="a" * 64,
            malware_verdict=MalwareVerdict.CLEAN,
            media_type_verified=False,
            verified_at=NOW,
            verifier_version="scanner/1",
        ),
    ):
        with pytest.raises(CustodyError):
            require_extractable(evidence, expected_hash="a" * 64)


def test_derivatives_preserve_lineage_classification_and_replay_identity() -> None:
    require_derivative_classification(
        source=Classification.CONFIDENTIAL,
        derivative=Classification.RESTRICTED,
    )
    with pytest.raises(CustodyError, match="downgrade"):
        require_derivative_classification(
            source=Classification.CONFIDENTIAL,
            derivative=Classification.INTERNAL,
        )
    first = derivative_digest(
        source_hash="b" * 64,
        processor_key="plain-text",
        processor_version="2",
        policy_version=4,
    )
    assert first == derivative_digest(
        source_hash="b" * 64,
        processor_key="plain-text",
        processor_version="2",
        policy_version=4,
    )
    assert first != derivative_digest(
        source_hash="b" * 64,
        processor_key="plain-text",
        processor_version="3",
        policy_version=4,
    )
    chunks = build_chunks(
        source_version_id=uuid4(),
        derivative_id=uuid4(),
        texts=("first", "second"),
        classification=Classification.CONFIDENTIAL,
        policy_version=4,
    )
    assert [chunk.position for chunk in chunks] == [0, 1]
    assert len({chunk.content_hash for chunk in chunks}) == 2


def test_legal_hold_and_retention_override_deletion() -> None:
    assert (
        deletion_disposition(
            now=NOW,
            legal_hold=True,
            retain_until=None,
        )
        is DeletionDisposition.BLOCKED_LEGAL_HOLD
    )
    assert (
        deletion_disposition(
            now=NOW,
            legal_hold=False,
            retain_until=NOW + timedelta(days=1),
        )
        is DeletionDisposition.BLOCKED_RETENTION
    )
    assert (
        deletion_disposition(
            now=NOW,
            legal_hold=False,
            retain_until=NOW - timedelta(seconds=1),
        )
        is DeletionDisposition.ELIGIBLE
    )


async def test_extraction_job_adapter_uses_typed_h3_02_idempotent_envelope() -> None:
    class Jobs:
        def __init__(self) -> None:
            self.command = None

        async def enqueue(self, command, *, now):
            self.command = command
            return type("Job", (), {"id": command.job_id})()

    jobs = Jobs()
    version_id = uuid4()
    adapter = DurableExtractionJobAdapter(
        jobs,
        definition_id=uuid4(),
        id_factory=lambda: UUID("00000000-0000-0000-0000-000000000001"),
        clock=lambda: NOW,
    )
    job_id = await adapter.enqueue_extraction(version_id, "d" * 64)
    assert job_id == UUID("00000000-0000-0000-0000-000000000001")
    assert jobs.command.command_type == "documents.extract"
    assert jobs.command.payload == {
        "source_version_id": str(version_id),
        "input_digest": "d" * 64,
    }
    assert jobs.command.idempotency_key == f"document-extraction:{version_id}:{'d' * 64}"


async def test_deletion_job_adapter_uses_typed_h3_02_idempotent_envelope() -> None:
    class Jobs:
        def __init__(self) -> None:
            self.command = None

        async def enqueue(self, command, *, now):
            self.command = command
            return type("Job", (), {"id": command.job_id})()

    jobs = Jobs()
    deletion_id, document_id = uuid4(), uuid4()
    adapter = DurableDeletionJobAdapter(
        jobs,
        definition_id=uuid4(),
        id_factory=lambda: UUID("00000000-0000-0000-0000-000000000002"),
        clock=lambda: NOW,
    )
    job_id = await adapter.enqueue_deletion(deletion_id, document_id)
    assert job_id == UUID("00000000-0000-0000-0000-000000000002")
    assert jobs.command.command_type == "documents.delete"
    assert jobs.command.payload == {
        "deletion_id": str(deletion_id),
        "document_id": str(document_id),
    }
    assert jobs.command.idempotency_key == f"document-deletion:{deletion_id}"
