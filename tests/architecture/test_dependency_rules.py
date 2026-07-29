"""Executable module-boundary checks for H0-01."""

from pathlib import Path

from tests.architecture.fitness import (
    check_domain_framework_independence,
    check_provider_sdk_confinement,
    python_sources,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPOSITORY_ROOT / "app"


def test_fit_arch_001_provider_sdks_are_confined_to_adapters() -> None:
    """FIT-ARCH-001 rejects Google SDK imports outside integration adapters."""

    violations = check_provider_sdk_confinement(
        python_sources(APP_ROOT),
        repository_root=REPOSITORY_ROOT,
    )

    assert not violations, "\n".join(str(violation) for violation in violations)


def test_fit_arch_002_domain_code_is_framework_independent() -> None:
    """FIT-ARCH-002 rejects framework and provider imports from domain packages."""

    violations = check_domain_framework_independence(
        python_sources(APP_ROOT),
        repository_root=REPOSITORY_ROOT,
    )

    assert not violations, "\n".join(str(violation) for violation in violations)
