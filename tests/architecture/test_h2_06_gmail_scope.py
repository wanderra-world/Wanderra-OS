from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_h2_06_is_provider_neutral_outside_the_adapter() -> None:
    module = ROOT / "app" / "email_capability"
    assert module.is_dir()
    for path in module.glob("*.py"):
        source = path.read_text().lower()
        assert "google" not in source
        assert "gmail" not in source


def test_h2_06_does_not_start_later_slices() -> None:
    source = "\n".join(
        path.read_text().lower()
        for path in (ROOT / "app" / "email_capability").glob("*.py")
    )
    forbidden = ("calendarport", "storageport", "webhook", "scheduler", "worker")
    assert not any(term in source for term in forbidden)


def test_h2_06_sdk_adapter_is_confined_to_integrations() -> None:
    adapter = ROOT / "app/integrations/gmail/adapter.py"
    assert adapter.is_file()
    assert "GmailEmailAdapter" in adapter.read_text()
