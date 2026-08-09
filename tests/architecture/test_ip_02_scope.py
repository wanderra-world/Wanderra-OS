"""Architecture Fitness for the bounded IP-02 Gmail OAuth implementation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ip_02_reuses_h2_and_adds_no_schema_or_future_provider() -> None:
    guide = (ROOT / "IMPLEMENTATION_GUIDE.md").read_text()
    evidence = (ROOT / "IP_02_ACCEPTANCE_EVIDENCE.md").read_text()
    migrations = tuple((ROOT / "alembic" / "versions").glob("*.py"))

    assert "### IP-02 Gmail OAuth Workspace Connection" in guide
    assert "Migration:** None" in evidence
    assert any("0032" in path.name for path in migrations)
    assert not any("ip_02" in path.name.lower() for path in migrations)
    assert "adds no connection, credential, OAuth transaction" in evidence
    assert "No real Gmail account connection is claimed" in evidence


def test_ip_02_provider_code_stays_out_of_provider_neutral_core() -> None:
    core = "\n".join(
        path.read_text()
        for directory in ("integration_layer", "connections", "oauth_transactions")
        for path in (ROOT / "app" / directory).glob("*.py")
    ).lower()
    assert "googleapiclient" not in core
    assert "google_auth_oauthlib" not in core
    assert "gmailoauth" not in core


def test_ip_02_does_not_authorize_future_slices() -> None:
    evidence = (ROOT / "IP_02_ACCEPTANCE_EVIDENCE.md").read_text()
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
        "business-agent",
    ):
        assert excluded in evidence
