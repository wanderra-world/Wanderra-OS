"""Event, concurrency, idempotency, and replay matrix for H0-13."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from tests.architecture.event_replay_prototype import (
    Aggregate,
    Command,
    CommandHandler,
    ConcurrencyConflict,
    ConsumerResult,
    Event,
    EventConsumer,
    EventContractError,
    EventSchema,
    EventSchemaRegistry,
    EventStore,
    ExternalEffectExecutor,
    IdempotencyConflict,
    MockExternalProvider,
    ReplayService,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def setup_handler() -> tuple[EventStore, CommandHandler, Aggregate]:
    store = EventStore()
    aggregate = Aggregate(
        id=uuid4(),
        workspace_id=uuid4(),
        aggregate_type="counter",
        version=0,
        value=0,
    )
    store.aggregates[aggregate.id] = aggregate
    return store, CommandHandler(store), aggregate


def command(
    aggregate: Aggregate,
    *,
    actor_id: UUID | None = None,
    expected_version: int = 0,
    amount: int = 1,
    key: str = "command-001",
) -> Command:
    return Command(
        workspace_id=aggregate.workspace_id,
        actor_id=actor_id or uuid4(),
        aggregate_id=aggregate.id,
        command_type="increment_counter",
        expected_version=expected_version,
        payload={"amount": amount},
        idempotency_key=key,
        correlation_id=uuid4(),
    )


def schemas() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    registry.register(
        EventSchema(
            event_type="counter.incremented",
            major_version=1,
            payload_fields=frozenset({"amount", "value"}),
        )
    )
    return registry


def event(
    *,
    workspace_id: UUID | None = None,
    aggregate_id: UUID | None = None,
    sequence: int = 1,
    schema_version: str = "1.0",
) -> Event:
    return Event(
        event_id=uuid4(),
        event_type="counter.incremented",
        schema_version=schema_version,
        workspace_id=workspace_id or uuid4(),
        aggregate_type="counter",
        aggregate_id=aggregate_id or uuid4(),
        aggregate_sequence=sequence,
        actor_id=uuid4(),
        delegation_id=None,
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=NOW,
        recorded_at=NOW,
        classification="internal",
        payload={"amount": 1, "value": sequence},
    )


def test_fit_event_001_event_envelope_contains_required_context() -> None:
    """FIT-EVENT-001 preserves the complete versioned event envelope."""

    _, handler, aggregate = setup_handler()
    outcome = handler.execute(command(aggregate), now=NOW)
    produced = outcome.event

    assert produced.event_id
    assert produced.event_type == "counter.incremented"
    assert produced.schema_version == "1.0"
    assert produced.workspace_id == aggregate.workspace_id
    assert produced.aggregate_id == aggregate.id
    assert produced.aggregate_sequence == 1
    assert produced.actor_id
    assert produced.correlation_id
    assert produced.classification == "internal"


def test_fit_event_002_state_audit_and_outbox_commit_atomically() -> None:
    """FIT-EVENT-002 commits state, audit, outbox, and idempotency together."""

    store, handler, aggregate = setup_handler()
    outcome = handler.execute(command(aggregate), now=NOW)

    assert store.aggregates[aggregate.id] == outcome.aggregate
    assert store.audit[0].resulting_version == 1
    assert store.outbox == [outcome.event]
    assert len(store.idempotency) == 1


def test_fit_event_003_transaction_failure_rolls_back_every_record() -> None:
    """FIT-EVENT-003 prevents partial state/audit/outbox commits."""

    store, handler, aggregate = setup_handler()
    with pytest.raises(EventContractError, match="injected"):
        handler.execute(
            command(aggregate),
            now=NOW,
            fail_before_commit=True,
        )

    assert store.aggregates[aggregate.id] == aggregate
    assert store.audit == []
    assert store.outbox == []
    assert store.idempotency == {}


def test_fit_event_004_stale_expected_version_is_rejected() -> None:
    """FIT-EVENT-004 enforces optimistic aggregate concurrency."""

    _, handler, aggregate = setup_handler()
    handler.execute(command(aggregate), now=NOW)

    with pytest.raises(ConcurrencyConflict, match="precondition"):
        handler.execute(
            command(aggregate, actor_id=uuid4(), key="command-002"),
            now=NOW,
        )


def test_fit_event_005_concurrent_writers_cannot_lose_updates() -> None:
    """FIT-EVENT-005 permits one winner for two concurrent version-zero writes."""

    store, handler, aggregate = setup_handler()
    barrier = Barrier(2)

    def run(key: str) -> str:
        barrier.wait()
        try:
            handler.execute(command(aggregate, key=key), now=NOW)
        except ConcurrencyConflict:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(run, ("concurrent-1", "concurrent-2")))

    assert sorted(results) == ["committed", "conflict"]
    assert store.aggregates[aggregate.id].version == 1
    assert len(store.outbox) == 1


def test_fit_event_006_exact_command_retry_returns_original_outcome() -> None:
    """FIT-EVENT-006 deduplicates exact caller retries."""

    store, handler, aggregate = setup_handler()
    actor_id = uuid4()
    original_command = command(aggregate, actor_id=actor_id)
    first = handler.execute(original_command, now=NOW)
    second = handler.execute(original_command, now=NOW)

    assert second == first
    assert len(store.outbox) == 1
    assert store.aggregates[aggregate.id].value == 1


def test_fit_event_007_changed_command_retry_is_rejected() -> None:
    """FIT-EVENT-007 rejects changed input under an existing scoped key."""

    _, handler, aggregate = setup_handler()
    actor_id = uuid4()
    handler.execute(command(aggregate, actor_id=actor_id), now=NOW)

    with pytest.raises(IdempotencyConflict, match="changed input"):
        handler.execute(
            command(aggregate, actor_id=actor_id, amount=2),
            now=NOW,
        )


def test_fit_event_008_idempotency_is_scoped_by_workspace_actor_and_command() -> None:
    """FIT-EVENT-008 prevents one caller's key from affecting another caller."""

    store, handler, aggregate = setup_handler()
    first = command(aggregate, actor_id=uuid4(), key="shared-key")
    handler.execute(first, now=NOW)
    current = store.aggregates[aggregate.id]
    second = command(
        current,
        actor_id=uuid4(),
        expected_version=1,
        key="shared-key",
    )
    handler.execute(second, now=NOW)

    assert store.aggregates[aggregate.id].version == 2
    assert len(store.idempotency) == 2


def test_fit_event_009_consumer_inbox_deduplicates_delivery() -> None:
    """FIT-EVENT-009 protects at-least-once delivery from duplicate processing."""

    handled: list[UUID] = []
    consumer = EventConsumer(
        name="projection",
        schemas=schemas(),
        handler=lambda delivered: handled.append(delivered.event_id),
    )
    delivered = event()

    assert consumer.process(delivered) is ConsumerResult.PROCESSED
    assert consumer.process(delivered) is ConsumerResult.DUPLICATE
    assert handled == [delivered.event_id]


def test_fit_event_010_failed_handler_retries_without_false_inbox_success() -> None:
    """FIT-EVENT-010 preserves at-least-once retry after transient failure."""

    calls = 0

    def transient(_event: Event) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")

    consumer = EventConsumer(
        name="projection",
        schemas=schemas(),
        handler=transient,
    )
    delivered = event()

    assert consumer.process(delivered) is ConsumerResult.RETRY
    assert delivered.event_id not in consumer.inbox
    assert consumer.process(delivered) is ConsumerResult.PROCESSED
    assert calls == 2


def test_fit_event_011_sequence_gap_waits_for_repair() -> None:
    """FIT-EVENT-011 prevents out-of-order projection updates."""

    workspace_id = uuid4()
    aggregate_id = uuid4()
    handled: list[int] = []
    consumer = EventConsumer(
        name="ordered-projection",
        schemas=schemas(),
        handler=lambda delivered: handled.append(delivered.aggregate_sequence),
    )

    assert consumer.process(
        event(
            workspace_id=workspace_id,
            aggregate_id=aggregate_id,
            sequence=2,
        )
    ) is ConsumerResult.GAP
    assert handled == []
    assert len(consumer.pending_gaps) == 1


def test_fit_event_012_schema_evolution_within_major_is_additive() -> None:
    """FIT-EVENT-012 rejects breaking changes under an existing major version."""

    registry = schemas()
    registry.register(
        EventSchema(
            event_type="counter.incremented",
            major_version=1,
            payload_fields=frozenset({"amount", "value", "reason"}),
        )
    )
    with pytest.raises(EventContractError, match="must be additive"):
        registry.register(
            EventSchema(
                event_type="counter.incremented",
                major_version=1,
                payload_fields=frozenset({"value"}),
            )
        )


def test_fit_event_013_unknown_schema_version_is_quarantined() -> None:
    """FIT-EVENT-013 stops unknown event meanings from reaching handlers."""

    handled: list[UUID] = []
    consumer = EventConsumer(
        name="projection",
        schemas=schemas(),
        handler=lambda delivered: handled.append(delivered.event_id),
    )
    unknown = event(schema_version="2.0")

    assert consumer.process(unknown) is ConsumerResult.QUARANTINED
    assert consumer.quarantine == [unknown]
    assert handled == []


def test_fit_event_014_poison_event_enters_visible_dead_letter() -> None:
    """FIT-EVENT-014 moves repeatedly failing events to operator-visible DLQ."""

    consumer = EventConsumer(
        name="projection",
        schemas=schemas(),
        handler=lambda _event: (_ for _ in ()).throw(RuntimeError("poison")),
        maximum_attempts=2,
    )
    poison = event()

    assert consumer.process(poison) is ConsumerResult.RETRY
    assert consumer.process(poison) is ConsumerResult.DEAD_LETTER
    assert consumer.dead_letters[0].event_id == poison.event_id
    assert consumer.dead_letters[0].attempts == 2


def test_fit_event_015_replay_requires_privilege_and_workspace_scope() -> None:
    """FIT-EVENT-015 denies unauthorized or cross-workspace replay."""

    delivered = event()
    consumer = EventConsumer(
        name="projection",
        schemas=schemas(),
        handler=lambda _event: None,
    )
    replay = ReplayService()

    with pytest.raises(EventContractError, match="privileged"):
        replay.replay(
            (delivered,),
            workspace_id=delivered.workspace_id,
            actor_id=uuid4(),
            privileged=False,
            dry_run=False,
            consumer=consumer,
        )
    with pytest.raises(EventContractError, match="cross workspace"):
        replay.replay(
            (delivered,),
            workspace_id=uuid4(),
            actor_id=uuid4(),
            privileged=True,
            dry_run=False,
            consumer=consumer,
        )


def test_fit_event_016_replay_is_audited_and_dry_runnable() -> None:
    """FIT-EVENT-016 records dry-run intent without invoking the consumer."""

    delivered = event()
    handled: list[UUID] = []
    consumer = EventConsumer(
        name="projection",
        schemas=schemas(),
        handler=lambda item: handled.append(item.event_id),
    )
    replay = ReplayService()

    result = replay.replay(
        (delivered,),
        workspace_id=delivered.workspace_id,
        actor_id=uuid4(),
        privileged=True,
        dry_run=True,
        consumer=consumer,
    )

    assert result == ()
    assert handled == []
    assert replay.audit[0].dry_run
    assert replay.audit[0].event_ids == (delivered.event_id,)


def test_fit_event_017_replay_does_not_duplicate_processed_side_effect() -> None:
    """FIT-EVENT-017 applies inbox protection during privileged replay."""

    delivered = event()
    handled: list[UUID] = []
    consumer = EventConsumer(
        name="side-effect",
        schemas=schemas(),
        handler=lambda item: handled.append(item.event_id),
    )
    assert consumer.process(delivered) is ConsumerResult.PROCESSED

    result = ReplayService().replay(
        (delivered,),
        workspace_id=delivered.workspace_id,
        actor_id=uuid4(),
        privileged=True,
        dry_run=False,
        consumer=consumer,
    )

    assert result == (ConsumerResult.DUPLICATE,)
    assert handled == [delivered.event_id]


def test_fit_event_018_external_effect_is_idempotent_and_verified() -> None:
    """FIT-EVENT-018 protects provider writes with idempotency and verification."""

    delivered = event()
    provider = MockExternalProvider()
    executor = ExternalEffectExecutor(provider)

    executor.execute(delivered, value="updated", expected_version=0)
    executor.execute(delivered, value="updated", expected_version=0)

    assert provider.effects == 1
    assert provider.fetch() == (1, "updated")
    assert executor.reconciliation == []


def test_fit_event_019_external_precondition_failure_blocks_write() -> None:
    """FIT-EVENT-019 prevents blind external overwrite."""

    provider = MockExternalProvider()
    executor = ExternalEffectExecutor(provider)

    with pytest.raises(ConcurrencyConflict, match="provider precondition"):
        executor.execute(event(), value="updated", expected_version=1)
    assert provider.effects == 0


def test_fit_event_020_external_verification_failure_requests_reconciliation() -> None:
    """FIT-EVENT-020 records provider divergence for reconciliation."""

    delivered = event()
    provider = MockExternalProvider()
    provider.drift_after_write = True
    executor = ExternalEffectExecutor(provider)

    with pytest.raises(EventContractError, match="reconciliation required"):
        executor.execute(delivered, value="updated", expected_version=0)
    assert executor.reconciliation == [delivered.event_id]
