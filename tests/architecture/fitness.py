"""Reusable architecture fitness rules for Atlas.

Each rule ID maps to the contract in H0_FOUNDATION_SPEC.md section 15.
"""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ImportReference:
    """One absolute import discovered in a Python source file."""

    source: Path
    module: str
    line: int


@dataclass(frozen=True, slots=True)
class FitnessViolation:
    """A stable, actionable architecture fitness-rule violation."""

    rule_id: str
    source: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.rule_id} {self.source}:{self.line}: {self.message}"


def python_sources(root: Path) -> tuple[Path, ...]:
    """Return deterministic production Python sources below ``root``."""

    return tuple(
        path
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def imported_modules(source: Path) -> tuple[ImportReference, ...]:
    """Parse absolute imports from one Python source file."""

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    references: list[ImportReference] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            references.extend(
                ImportReference(source=source, module=alias.name, line=node.lineno)
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            references.append(
                ImportReference(source=source, module=node.module, line=node.lineno)
            )

    return tuple(references)


def check_provider_sdk_confinement(
    sources: Iterable[Path],
    *,
    repository_root: Path,
) -> tuple[FitnessViolation, ...]:
    """Enforce FIT-ARCH-001: Google SDKs remain inside provider adapters."""

    violations: list[FitnessViolation] = []
    allowed_root = repository_root / "app" / "integrations"

    for source in sources:
        for reference in imported_modules(source):
            if not reference.module.startswith(("google", "googleapiclient")):
                continue
            if source.is_relative_to(allowed_root):
                continue
            violations.append(
                FitnessViolation(
                    rule_id="FIT-ARCH-001",
                    source=source.relative_to(repository_root),
                    line=reference.line,
                    message=(
                        f"Google SDK import {reference.module!r} must remain under "
                        "app/integrations"
                    ),
                )
            )

    return tuple(violations)


def check_domain_framework_independence(
    sources: Iterable[Path],
    *,
    repository_root: Path,
) -> tuple[FitnessViolation, ...]:
    """Enforce FIT-ARCH-002: domain packages do not import frameworks or SDKs."""

    forbidden_roots = {
        "alembic",
        "asyncpg",
        "fastapi",
        "google",
        "googleapiclient",
        "openai",
        "sqlalchemy",
    }
    violations: list[FitnessViolation] = []

    for source in sources:
        relative = source.relative_to(repository_root)
        if "domain" not in relative.parts:
            continue
        for reference in imported_modules(source):
            imported_root = reference.module.split(".", maxsplit=1)[0]
            if imported_root not in forbidden_roots:
                continue
            violations.append(
                FitnessViolation(
                    rule_id="FIT-ARCH-002",
                    source=relative,
                    line=reference.line,
                    message=(
                        f"domain code must not import framework/provider module "
                        f"{reference.module!r}"
                    ),
                )
            )

    return tuple(violations)


DEFERRED_MODULE_NAMES = frozenset(
    {
        "advanced_workflows",
        "commerce",
        "crm",
        "finance",
        "knowledge_graph",
        "properties",
        "recommendations",
        "shipments",
        "vehicles",
    }
)

LEGACY_PHASE1_AGENT_FILES = frozenset(
    {
        Path("app/agents/__init__.py"),
        Path("app/agents/atlas.py"),
    }
)


def check_canonical_scope(
    sources: Iterable[Path],
    *,
    repository_root: Path,
) -> tuple[FitnessViolation, ...]:
    """Enforce FIT-SCOPE-001: deferred modules cannot enter the Phase 2 core."""

    violations: list[FitnessViolation] = []
    for source in sources:
        relative = source.relative_to(repository_root)
        module_parts = {
            part.removesuffix(".py").casefold()
            for part in relative.parts
        }
        deferred = sorted(module_parts & DEFERRED_MODULE_NAMES)
        if deferred:
            violations.append(
                FitnessViolation(
                    rule_id="FIT-SCOPE-001",
                    source=relative,
                    line=1,
                    message=(
                        f"deferred module {deferred[0]!r} is outside the canonical "
                        "Phase 2 core"
                    ),
                )
            )
        if (
            relative.parts[:2] == ("app", "agents")
            and relative not in LEGACY_PHASE1_AGENT_FILES
        ):
            violations.append(
                FitnessViolation(
                    rule_id="FIT-SCOPE-001",
                    source=relative,
                    line=1,
                    message=(
                        "new broad agent modules are deferred; only the frozen "
                        "Phase 1 compatibility surface is permitted"
                    ),
                )
            )
    return tuple(violations)


def check_business_provider_independence(
    sources: Iterable[Path],
    *,
    repository_root: Path,
) -> tuple[FitnessViolation, ...]:
    """Enforce FIT-SCOPE-002: core business modules do not depend on adapters."""

    business_roots = {"domain", "memory", "services"}
    violations: list[FitnessViolation] = []
    for source in sources:
        relative = source.relative_to(repository_root)
        if len(relative.parts) < 2 or relative.parts[1] not in business_roots:
            continue
        for reference in imported_modules(source):
            if not reference.module.startswith("app.integrations"):
                continue
            violations.append(
                FitnessViolation(
                    rule_id="FIT-SCOPE-002",
                    source=relative,
                    line=reference.line,
                    message=(
                        "business modules must depend on provider-neutral ports, "
                        f"not {reference.module!r}"
                    ),
                )
            )
    return tuple(violations)


def check_postgresql_platform(pyproject: Path) -> tuple[FitnessViolation, ...]:
    """Enforce FIT-SCOPE-003: PostgreSQL remains the initial record/search platform."""

    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    dependencies = tuple(
        dependency.casefold()
        for dependency in project.get("dependencies", ())
    )
    required = {"asyncpg", "sqlalchemy"}
    prohibited = {
        "elasticsearch",
        "meilisearch",
        "motor",
        "neo4j",
        "opensearch",
        "pymongo",
        "qdrant",
        "typesense",
        "weaviate",
    }
    violations: list[FitnessViolation] = []
    for dependency in sorted(prohibited):
        if any(item.startswith(dependency) for item in dependencies):
            violations.append(
                FitnessViolation(
                    rule_id="FIT-SCOPE-003",
                    source=pyproject.name,
                    line=1,
                    message=(
                        f"premature data/search platform dependency {dependency!r} "
                        "requires measured extraction evidence and an ADR"
                    ),
                )
            )
    for dependency in sorted(required):
        if not any(item.startswith(dependency) for item in dependencies):
            violations.append(
                FitnessViolation(
                    rule_id="FIT-SCOPE-003",
                    source=pyproject.name,
                    line=1,
                    message=f"required PostgreSQL platform dependency {dependency!r} is missing",
                )
            )
    return tuple(violations)


def check_postgresql_default(config_source: Path) -> tuple[FitnessViolation, ...]:
    """Enforce FIT-SCOPE-004: the default record platform remains PostgreSQL."""

    tree = ast.parse(
        config_source.read_text(encoding="utf-8"),
        filename=str(config_source),
    )
    database_defaults = tuple(
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "database_url"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )
    if (
        len(database_defaults) == 1
        and database_defaults[0].startswith("postgresql+asyncpg://")
    ):
        return ()
    return (
        FitnessViolation(
            rule_id="FIT-SCOPE-004",
            source=config_source.name,
            line=1,
            message="default database URL must use PostgreSQL with asyncpg",
        ),
    )
