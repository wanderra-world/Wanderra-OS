"""Unit evidence for deterministic H1-08 messaging contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.messaging import CommandEnvelope, EventEnvelope


def command(**changes: object) -> CommandEnvelope:
    values: dict[str, object] = {
        "workspace_id": uuid4(),
        "actor_id": uuid4(),
        "command_type": "project.renamed",
        "idempotency_key": "caller-key-1",
        "aggregate_type": "project",
        "aggregate_id": uuid4(),
        "expected_version": 0,
        "correlation_id": "correlation-1",
        "payload": {"name": "Atlas"},
    }
    values.update(changes)
    return CommandEnvelope(**values)  # type: ignore[arg-type]


def test_command_digest_is_canonical_and_detects_changed_input() -> None:
    first = command(payload={"name": "Atlas", "priority": 1})
    reordered = command(
        workspace_id=first.workspace_id,
        actor_id=first.actor_id,
        aggregate_id=first.aggregate_id,
        payload={"priority": 1, "name": "Atlas"},
    )
    assert first.request_digest() == reordered.request_digest()
    changed = command(
        workspace_id=first.workspace_id,
        actor_id=first.actor_id,
        aggregate_id=first.aggregate_id,
        payload={"priority": 2, "name": "Atlas"},
    )
    assert changed.request_digest() != first.request_digest()


def test_command_contract_is_immutable_and_validates_preconditions() -> None:
    value = command()
    with pytest.raises(FrozenInstanceError):
        value.expected_version = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="expected version"):
        command(expected_version=-1)
    with pytest.raises(ValueError, match="idempotency key"):
        command(idempotency_key=" ")


def test_event_contract_requires_version_sequence_and_trace_context() -> None:
    values = {
        "event_id": uuid4(),
        "event_type": "project.renamed",
        "schema_major": 1,
        "schema_minor": 0,
        "workspace_id": uuid4(),
        "aggregate_type": "project",
        "aggregate_id": uuid4(),
        "aggregate_sequence": 1,
        "actor_id": uuid4(),
        "correlation_id": "correlation-1",
        "occurred_at": datetime.now(UTC),
        "classification": "internal",
        "payload": {"name": "Atlas"},
    }
    event = EventEnvelope(**values)
    assert event.schema_major == 1
    with pytest.raises(ValueError, match="schema version"):
        EventEnvelope(**(values | {"schema_major": 0}))
    with pytest.raises(ValueError, match="sequence"):
        EventEnvelope(**(values | {"aggregate_sequence": 0}))
