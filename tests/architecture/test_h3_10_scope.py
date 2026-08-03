from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_10_is_provider_neutral_and_excludes_future_product_work() -> None:
    root = ROOT / "app" / "agent_platform"
    production = "\n".join(path.read_text() for path in root.rglob("*.py")).casefold()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar",
        "drive",
        "slack",
        "telegram",
        "whatsapp",
        "shopify",
        "stripe",
        "wanderra agent",
        "trading agent",
        "openai",
        "anthropic",
        "provider sdk",
        "subprocess",
        "exec(",
        "eval(",
    ):
        assert forbidden not in production
    assert "protocol" in production
    assert not (ROOT / "app" / "h4").exists()
    assert not (ROOT / "app" / "business_agents").exists()


def test_h3_10_migration_is_additive_forced_rls_and_guarded() -> None:
    text = (ROOT / "alembic" / "versions" / "0031_add_agent_platform.py").read_text()
    assert 'down_revision = "0030_h3_notification_center"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text
