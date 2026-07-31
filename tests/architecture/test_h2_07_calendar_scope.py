from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_h2_07_application_module_is_provider_neutral() -> None:
    module = ROOT / "app/calendar_capability"
    assert module.is_dir()
    source = "\n".join(path.read_text().lower() for path in module.glob("*.py"))
    assert "google" not in source
    assert "googleapiclient" not in source


def test_h2_07_sdk_adapter_is_confined_to_integrations() -> None:
    adapter = ROOT / "app/integrations/calendar/adapter.py"
    assert adapter.is_file()
    assert "GoogleCalendarAdapter" in adapter.read_text()


def test_h2_07_does_not_start_h2_08_or_runtime_processing() -> None:
    roots = (ROOT / "app/calendar_capability", ROOT / "app/integrations/calendar")
    source = "\n".join(
        path.read_text().lower()
        for root in roots
        for path in root.glob("*.py")
        if path.name != "service.py"
    )
    forbidden = (
        "storageport",
        "drive",
        "webhook",
        "push notification",
        "scheduler",
        "worker",
    )
    assert not any(term in source for term in forbidden)
