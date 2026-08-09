"""Architecture Fitness for the bounded IP-03 operator lifecycle."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ip_03_reuses_canonical_boundaries_and_adds_no_migration() -> None:
    source = (ROOT / "app/integrations/gmail/operator.py").read_text()
    api = (ROOT / "app/api/v1/gmail_connections.py").read_text()
    evidence = " ".join((ROOT / "IP_03_ACCEPTANCE_EVIDENCE.md").read_text().split())
    migrations = tuple((ROOT / "alembic/versions").glob("*.py"))

    for canonical in (
        "app.connections",
        "app.oauth_transactions",
        "app.connection_credentials",
        "app.identity",
        "app.memberships",
        "app.execution_context",
        "app.messaging",
    ):
        assert canonical in source or canonical in api
    assert "**Migration:** None" in evidence
    assert not any("ip_03" in migration.name.lower() for migration in migrations)


def test_ip_03_operator_contract_is_secret_free_and_workspace_bound() -> None:
    api = (ROOT / "app/api/v1/gmail_connections.py").read_text()
    evidence = (ROOT / "IP_03_ACCEPTANCE_EVIDENCE.md").read_text()

    assert 'Cookie(alias="__Host-atlas_session")' in api
    assert 'Cookie(alias="__Host-atlas_csrf")' in api
    assert "parse_workspace_hint(state_value)" in api
    assert "GmailConnectionResponse" in api
    assert "cannot serialize an access token" in evidence


def test_ip_03_keeps_later_scope_unauthorized() -> None:
    evidence = (ROOT / "IP_03_ACCEPTANCE_EVIDENCE.md").read_text()
    for excluded in (
        "Calendar",
        "Drive",
        "Contacts",
        "WhatsApp",
        "Stripe",
        "LinkedIn",
        "Facebook",
        "Instagram",
        "TikTok",
        "YouTube",
        "CRM",
        "UI/product",
        "workflow",
        "business-agent",
    ):
        assert excluded in evidence


def test_ip_03_candidate_is_traceable_without_claiming_acceptance() -> None:
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    status = (ROOT / "PROJECT_STATUS.md").read_text()
    evidence = " ".join((ROOT / "IP_03_ACCEPTANCE_EVIDENCE.md").read_text().split())

    assert "IP-03 implementation candidate is ready for review" in index
    assert (
        "IP-03 Operator-facing Gmail Connection Lifecycle (Implementation candidate)"
        in status
    )
    assert "pending pull-request review and protected checks" in evidence
    assert "No live Gmail authorization is claimed" in evidence
