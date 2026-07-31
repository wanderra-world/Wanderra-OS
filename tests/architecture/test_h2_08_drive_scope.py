from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_h2_08_provider_neutral_and_sdk_confined() -> None:
    source = "\n".join(
        p.read_text().lower() for p in (ROOT / "app/storage_capability").glob("*.py")
    )
    assert "google" not in source and "googleapiclient" not in source
    assert (ROOT / "app/integrations/drive/adapter.py").is_file()


def test_h2_08_does_not_start_h2_09_or_document_custody() -> None:
    source = "\n".join(
        p.read_text().lower() for p in (ROOT / "app/storage_capability").glob("*.py")
    )
    assert not any(
        term in source
        for term in (
            "cutover threshold",
            "backfill",
            "document custody",
            "change feed",
            "worker",
            "webhook",
        )
    )
