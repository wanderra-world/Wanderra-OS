"""Red-first contract tests for the H3-05 governed Memory Manager."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.documents.contracts import Classification
from app.memory.governance_contracts import (
    ConsolidationCreate,
    MemoryCreate,
    MemoryError,
    MemoryFeedbackCreate,
    MemoryFeedbackKind,
    MemoryKind,
    MemorySource,
    MemorySourceKind,
    MemoryStatus,
    MemoryVisibility,
    ModelRoute,
    effective_classification,
    evaluate_status,
    require_model_egress,
)

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


def _source(*, classification: Classification = Classification.INTERNAL) -> MemorySource:
    return MemorySource(
        source_id=uuid4(),
        source_kind=MemorySourceKind.KNOWLEDGE_CLAIM,
        source_version=1,
        source_digest="a" * 64,
        classification=classification,
        policy_version=1,
    )


def _command(*, source: MemorySource | None = None) -> MemoryCreate:
    return MemoryCreate(
        memory_id=uuid4(),
        memory_kind=MemoryKind.DECISION,
        content="Use the signed custody manifest for restoration.",
        subject_resource_id=uuid4(),
        owner_user_id=uuid4(),
        visibility=MemoryVisibility.PRIVATE,
        confidence=0.9,
        classification=Classification.INTERNAL,
        policy_version=1,
        creation_method="human_confirmed",
        expires_at=NOW + timedelta(days=90),
        sources=(source or _source(),),
    )


def test_memory_requires_typed_provenance_and_canonical_digest() -> None:
    source = _source()
    command = _command(source=source)
    assert len(command.identity_digest) == 64
    assert command.identity_digest == replace(command, memory_id=uuid4()).identity_digest
    with pytest.raises(MemoryError, match="source"):
        MemoryCreate(
            memory_id=uuid4(),
            memory_kind=MemoryKind.SUMMARY,
            content="unattributed",
            subject_resource_id=None,
            owner_user_id=uuid4(),
            visibility=MemoryVisibility.PRIVATE,
            confidence=0.5,
            classification=Classification.INTERNAL,
            policy_version=1,
            creation_method="derived",
            expires_at=None,
            sources=(),
        )


def test_memory_classification_cannot_be_lower_than_sources() -> None:
    restricted = _source(classification=Classification.RESTRICTED)
    with pytest.raises(MemoryError, match="downgrade"):
        _command(source=restricted)
    assert effective_classification((Classification.INTERNAL, Classification.RESTRICTED)) is (
        Classification.RESTRICTED
    )


def test_memory_lifecycle_expiry_and_pinning_are_deterministic() -> None:
    expires = NOW + timedelta(days=1)
    assert evaluate_status(MemoryStatus.ACTIVE, expires, False, NOW) is MemoryStatus.ACTIVE
    assert evaluate_status(MemoryStatus.ACTIVE, expires, False, expires) is MemoryStatus.EXPIRED
    assert evaluate_status(MemoryStatus.ACTIVE, expires, True, expires) is MemoryStatus.ACTIVE
    assert (
        evaluate_status(MemoryStatus.INVALIDATED, expires, True, expires)
        is MemoryStatus.INVALIDATED
    )


def test_consolidation_is_versioned_deterministic_and_requires_distinct_inputs() -> None:
    first = UUID("00000000-0000-0000-0000-000000000001")
    second = UUID("00000000-0000-0000-0000-000000000002")
    command = ConsolidationCreate(
        memory_id=uuid4(),
        input_memory_ids=(second, first),
        processor_key="atlas.memory.consolidate",
        processor_version="1",
        policy_version=2,
    )
    assert command.input_memory_ids == (first, second)
    assert len(command.input_digest) == 64
    with pytest.raises(MemoryError, match="distinct"):
        ConsolidationCreate(
            memory_id=uuid4(),
            input_memory_ids=(first, first),
            processor_key="atlas.memory.consolidate",
            processor_version="1",
            policy_version=2,
        )


def test_feedback_is_typed_minimized_and_requires_reason() -> None:
    feedback = MemoryFeedbackCreate(
        feedback_id=uuid4(),
        memory_id=uuid4(),
        kind=MemoryFeedbackKind.INCORRECT,
        reason="The source decision was superseded.",
    )
    assert feedback.kind is MemoryFeedbackKind.INCORRECT
    with pytest.raises(MemoryError, match="reason"):
        MemoryFeedbackCreate(
            feedback_id=uuid4(),
            memory_id=uuid4(),
            kind=MemoryFeedbackKind.HELPFUL,
            reason=" ",
        )


def test_sensitive_memory_model_egress_fails_closed() -> None:
    require_model_egress(Classification.CONFIDENTIAL, ModelRoute.PRIVATE)
    with pytest.raises(MemoryError, match="egress"):
        require_model_egress(Classification.RESTRICTED, ModelRoute.STANDARD)


def test_contract_rejects_naive_expiry_and_unbounded_content() -> None:
    command = _command()
    with pytest.raises(MemoryError, match="timezone"):
        MemoryCreate(
            **{
                **{
                    field: getattr(command, field)
                    for field in command.__dataclass_fields__
                    if field not in {"expires_at"}
                },
                "expires_at": datetime(2026, 8, 3),
            }
        )
    with pytest.raises(MemoryError, match="content"):
        MemoryCreate(
            **{
                **{
                    field: getattr(command, field)
                    for field in command.__dataclass_fields__
                    if field not in {"content"}
                },
                "content": "x" * 4097,
            }
        )
