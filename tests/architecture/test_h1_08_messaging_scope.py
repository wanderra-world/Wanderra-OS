"""Architecture fitness evidence for the bounded H1-08 slice."""

from __future__ import annotations

from pathlib import Path

from app.messaging.models import (
    AggregateVersion,
    AuditChainHead,
    CommandIdempotency,
    ConsumerSequence,
    EventQuarantine,
    InboxEvent,
)
from app.tenancy.models import AuditEvent, OutboxEvent

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic/versions/0012_add_audit_messaging.py"
MESSAGING = ROOT / "app/messaging"


def test_h1_08_reuses_canonical_audit_and_outbox_models() -> None:
    assert AuditEvent.__tablename__ == "audit_events"
    assert OutboxEvent.__tablename__ == "outbox_events"
    model_source = (MESSAGING / "models.py").read_text()
    assert "class AuditEvent" not in model_source
    assert "class OutboxEvent" not in model_source


def test_h1_08_persistence_is_workspace_scoped() -> None:
    for model in (
        AuditChainHead,
        CommandIdempotency,
        AggregateVersion,
        InboxEvent,
        ConsumerSequence,
        EventQuarantine,
    ):
        assert "workspace_id" in model.__table__.columns


def test_h1_08_migration_forces_rls_and_tamper_evidence() -> None:
    source = MIGRATION.read_text()
    for table in (
        "audit_chain_heads",
        "command_idempotency",
        "aggregate_versions",
        "inbox_events",
        "consumer_sequences",
        "event_quarantine",
    ):
        assert f'"{table}"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "CREATE TRIGGER audit_events_chain_insert" in source
    assert "CREATE FUNCTION verify_audit_chain" in source
    assert "audit_events_are_immutable" in source


def test_h1_08_does_not_select_future_runtime_infrastructure() -> None:
    source = "\n".join(
        path.read_text() for path in MESSAGING.glob("*.py")
    ).lower()
    for forbidden in (
        "kafka",
        "rabbitmq",
        "celery",
        "scheduler",
        "background job",
        "provider integration",
    ):
        assert forbidden not in source
