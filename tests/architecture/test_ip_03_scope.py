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


def test_ip_03_is_accepted_and_only_gmail_readiness_is_authorized() -> None:
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    status = (ROOT / "PROJECT_STATUS.md").read_text()
    evidence = " ".join((ROOT / "IP_03_ACCEPTANCE_EVIDENCE.md").read_text().split())

    assert "IP-03 Operator-facing Gmail Connection Lifecycle is Accepted" in index
    assert "IP-03 Operator-facing Gmail Connection Lifecycle (Accepted)" in status
    assert "Accepted and merged through PR #52 at `6a5eccd`" in evidence
    assert "Gmail operational readiness authorization" in (
        ROOT / "DECISIONS.md"
    ).read_text()
    normalized_index = " ".join(index.split())
    assert "Gmail operational readiness / operator authentication" in normalized_index
    assert "Accepted through PR #54" in normalized_index
    assert "No subsequent Integration Platform runtime slice is authorized" in normalized_index
    assert "MUST NOT create an authentication authority" in (
        ROOT / "IMPLEMENTATION_GUIDE.md"
    ).read_text()
    assert "No live Gmail authorization is claimed" in evidence
