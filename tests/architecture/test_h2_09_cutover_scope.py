from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_h2_09_does_not_remove_phase_one_fallback_or_start_h2_10() -> None:
    migration = (ROOT / "alembic/versions/0021_add_connection_cutover.py").read_text()
    assert "DROP TABLE gmail_credentials" not in migration
    assert "DROP TABLE calendar_credentials" not in migration
    assert "DROP TABLE drive_credentials" not in migration
    production = "\n".join(
        path.read_text(errors="ignore") for path in (ROOT / "app/connection_cutover").glob("*.py")
    )
    for forbidden in ("mock second provider", "Formal H2 Exit", "universal entity"):
        assert forbidden not in production


def test_recovery_manifest_includes_every_h2_tenant_table() -> None:
    source = (ROOT / "app/recovery/repository.py").read_text()
    required = {
        "connections",
        "connection_capability_grants",
        "connection_credentials",
        "credential_migration_inventory",
        "oauth_transactions",
        "provider_mirrors",
        "provider_external_references",
        "provider_mirror_comparisons",
        "provider_mirror_conflicts",
        "email_capability_routes",
        "email_shadow_comparisons",
        "calendar_capability_routes",
        "calendar_shadow_comparisons",
        "storage_capability_routes",
        "storage_shadow_comparisons",
        "connection_backfill_evidence",
        "capability_cutover_evidence",
    }
    assert required <= set(source.split('"'))
