"""Threat-specific P0.5 evidence register for Atlas H0."""

from __future__ import annotations

from tests.architecture.threat_review_prototype import (
    MitigationEvidence,
    Severity,
    Threat,
    Treatment,
)


def evidence(control: str, test_id: str, source: str) -> MitigationEvidence:
    return MitigationEvidence(
        control=control,
        test_id=test_id,
        source_path=f"tests/architecture/{source}",
    )


def h0_threats() -> tuple[Threat, ...]:
    """Return the reviewed T01–T14 register in stable threat-ID order."""

    return (
        Threat(
            threat_id="T01",
            description="Cross-workspace disclosure or mutation",
            risk_owner="Atlas Core Security",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("API/database", "tenant/tenant"),
            protected_assets=("tenant data", "workspace authorization context"),
            primary_controls=(
                "composite tenant keys",
                "forced PostgreSQL RLS",
                "typed transaction-local workspace context",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "missing workspace context denies access",
                    "FIT-TENANT-001",
                    "test_tenancy_isolation.py",
                ),
                evidence(
                    "forced RLS filters cross-workspace rows",
                    "FIT-TENANT-002",
                    "test_tenancy_isolation.py",
                ),
                evidence(
                    "composite foreign keys reject cross-workspace references",
                    "FIT-TENANT-003",
                    "test_tenancy_isolation.py",
                ),
                evidence(
                    "authorization denies workspace mismatch",
                    "FIT-AUTHZ-002",
                    "test_authorization_policy.py",
                ),
            ),
        ),
        Threat(
            threat_id="T02",
            description="Database pool reuse leaks tenant context",
            risk_owner="Atlas Data Platform",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("API/database", "worker/database"),
            protected_assets=("tenant isolation", "database connection pools"),
            primary_controls=(
                "transaction-local PostgreSQL settings",
                "clean pool checkout",
                "non-bypass runtime role",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "pool reuse clears transaction-local workspace context",
                    "FIT-TENANT-004",
                    "test_tenancy_isolation.py",
                ),
            ),
        ),
        Threat(
            threat_id="T03",
            description="Account takeover or stale authorization remains effective",
            risk_owner="Atlas Identity",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("client/API", "identity provider/Atlas"),
            protected_assets=("user identity", "sessions", "workspace authority"),
            primary_controls=(
                "hashed opaque sessions",
                "immediate revocation checks",
                "recent MFA for privileged access",
                "recovery-wide session invalidation",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "session revocation applies on the next transaction",
                    "FIT-SESSION-002",
                    "test_identity_lifecycle.py",
                ),
                evidence(
                    "privileged access requires recent MFA",
                    "FIT-SESSION-003",
                    "test_identity_lifecycle.py",
                ),
                evidence(
                    "recovery revokes all sessions and recovery tokens",
                    "FIT-RECOVERY-002",
                    "test_identity_lifecycle.py",
                ),
            ),
        ),
        Threat(
            threat_id="T04",
            description="Provider credentials or encryption keys are stolen",
            risk_owner="Atlas Security Engineering",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("Atlas/provider", "runtime/KMS"),
            protected_assets=("provider credentials", "data-encryption keys"),
            primary_controls=(
                "per-record authenticated envelope encryption",
                "narrow KMS roles",
                "context-bound additional authenticated data",
                "rotation and emergency disablement",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "per-record encryption excludes plaintext and raw keys",
                    "FIT-ENCRYPT-001",
                    "test_encryption_rotation.py",
                ),
                evidence(
                    "authenticated data binds credential security context",
                    "FIT-ENCRYPT-002",
                    "test_encryption_rotation.py",
                ),
                evidence(
                    "runtime cannot administer KMS keys",
                    "FIT-ENCRYPT-003",
                    "test_encryption_rotation.py",
                ),
                evidence(
                    "emergency connection handling revokes and records incident",
                    "FIT-ENCRYPT-008",
                    "test_encryption_rotation.py",
                ),
            ),
        ),
        Threat(
            threat_id="T05",
            description="Provider webhook is forged or replayed",
            risk_owner="Atlas Integrations",
            inherent_severity=Severity.HIGH,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("provider webhook/Atlas",),
            protected_assets=("sync integrity", "provider event routing"),
            primary_controls=(
                "no webhook ingress in the current H0 surface",
                "future ingress requires verification and inbox deduplication",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "canonical scope prevents premature integration surfaces",
                    "FIT-SCOPE-001",
                    "test_scope_fitness.py",
                ),
                evidence(
                    "consumer inbox deduplicates replayed delivery",
                    "FIT-EVENT-009",
                    "test_event_replay.py",
                ),
            ),
            remaining_gap=(
                "Provider-specific signature and timestamp validation must be added "
                "with the first webhook adapter."
            ),
        ),
        Threat(
            threat_id="T06",
            description="Provider conflict silently overwrites governed truth",
            risk_owner="Atlas Integrations",
            inherent_severity=Severity.HIGH,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("Atlas/provider",),
            protected_assets=("canonical business truth", "provider mirrors"),
            primary_controls=(
                "explicit authority policy",
                "conflict state instead of last-write-wins",
                "preconditions and post-write verification",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "ambiguous inbound change enters conflict",
                    "FIT-MIRROR-004",
                    "test_provider_conflicts.py",
                ),
                evidence(
                    "failed provider precondition refreshes without blind retry",
                    "FIT-MIRROR-008",
                    "test_provider_conflicts.py",
                ),
                evidence(
                    "post-write provider drift enters conflict",
                    "FIT-MIRROR-011",
                    "test_provider_conflicts.py",
                ),
            ),
        ),
        Threat(
            threat_id="T07",
            description="Malicious document or prompt manipulates Atlas execution",
            risk_owner="Atlas AI Security",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("untrusted content/extraction/model context",),
            protected_assets=("document custody", "AI instruction integrity"),
            primary_controls=(
                "quarantine and malware scanning",
                "MIME validation",
                "structural instruction/content separation",
                "trust labels",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "scan failure prevents document promotion",
                    "FIT-CUSTODY-005",
                    "test_document_custody.py",
                ),
                evidence(
                    "untrusted prompt content remains labeled data",
                    "FIT-AI-001",
                    "test_ai_security_review.py",
                ),
                evidence(
                    "retrieved content cannot expand tool permissions",
                    "FIT-AI-009",
                    "test_ai_security_review.py",
                ),
            ),
        ),
        Threat(
            threat_id="T08",
            description="Sensitive data is disclosed through model egress",
            risk_owner="Atlas AI Security",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("Atlas/model provider", "tenant/model context"),
            protected_assets=("confidential tenant data", "secrets", "AI logs"),
            primary_controls=(
                "permission and classification filtering",
                "secret exclusion and context minimization",
                "region/retention/training-aware model routing",
                "content-free logs",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "context excludes unauthorized, unsupported, and secret data",
                    "FIT-AI-002",
                    "test_ai_security_review.py",
                ),
                evidence(
                    "model route enforces egress policy",
                    "FIT-AI-005",
                    "test_ai_security_review.py",
                ),
                evidence(
                    "AI logs exclude prompts and retrieved content",
                    "FIT-AI-007",
                    "test_ai_security_review.py",
                ),
            ),
        ),
        Threat(
            threat_id="T09",
            description="Agent bypasses commands, permissions, or approval",
            risk_owner="Atlas Agent Platform",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("model intent/commands/side effects",),
            protected_assets=("command integrity", "external systems", "budgets"),
            primary_controls=(
                "registered tools only",
                "runtime authorization and delegation",
                "approval, resource-version, and budget checks",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "agent commands recheck every runtime control",
                    "FIT-AI-008",
                    "test_ai_security_review.py",
                ),
                evidence(
                    "retrieved content cannot expand tool permissions",
                    "FIT-AI-009",
                    "test_ai_security_review.py",
                ),
                evidence(
                    "new broad agent modules are detected",
                    "FIT-SCOPE-001",
                    "test_scope_fitness.py",
                ),
            ),
        ),
        Threat(
            threat_id="T10",
            description="Deletion leaves accessible derivatives or provider data",
            risk_owner="Atlas Data Governance",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("source/derivative stores", "Atlas/provider"),
            protected_assets=("erasure rights", "derived data", "backups"),
            primary_controls=(
                "transitive lineage traversal",
                "tombstoning and projection invalidation",
                "provider verification",
                "backup expiry or key erasure",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "erasure traverses all derivatives",
                    "FIT-LINEAGE-003",
                    "test_derivative_deletion.py",
                ),
                evidence(
                    "retrieval projections are invalidated",
                    "FIT-LINEAGE-006",
                    "test_derivative_deletion.py",
                ),
                evidence(
                    "unverified provider deletion is reported",
                    "FIT-LINEAGE-008",
                    "test_derivative_deletion.py",
                ),
                evidence(
                    "backups use governed deletion disposition",
                    "FIT-LINEAGE-009",
                    "test_derivative_deletion.py",
                ),
            ),
        ),
        Threat(
            threat_id="T11",
            description="Replay or retry duplicates a material side effect",
            risk_owner="Atlas Core Runtime",
            inherent_severity=Severity.HIGH,
            residual_severity=Severity.MODERATE,
            trust_boundaries=("event bus/consumer", "Atlas/provider"),
            protected_assets=("aggregate consistency", "external-action integrity"),
            primary_controls=(
                "scoped command idempotency",
                "consumer inbox deduplication",
                "privileged audited replay",
                "provider idempotency and verification",
            ),
            treatment=Treatment.MITIGATED,
            evidence_references=(
                evidence(
                    "exact command retry returns original outcome",
                    "FIT-EVENT-006",
                    "test_event_replay.py",
                ),
                evidence(
                    "replay does not duplicate processed side effect",
                    "FIT-EVENT-017",
                    "test_event_replay.py",
                ),
                evidence(
                    "external effect is idempotent and verified",
                    "FIT-EVENT-018",
                    "test_event_replay.py",
                ),
            ),
        ),
        Threat(
            threat_id="T12",
            description="Privileged actor tampers with audit evidence",
            risk_owner="Atlas Security Engineering",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.HIGH,
            trust_boundaries=("operator/audit store", "runtime/database"),
            protected_assets=("audit evidence", "security accountability"),
            primary_controls=(
                "atomic state/audit/outbox commit",
                "minimal deletion audit evidence",
                "future append-only audit role and chained export",
            ),
            treatment=Treatment.UNRESOLVED,
            evidence_references=(
                evidence(
                    "state, audit, and outbox commit atomically",
                    "FIT-EVENT-002",
                    "test_event_replay.py",
                ),
                evidence(
                    "erasure retains minimal audit evidence",
                    "FIT-LINEAGE-012",
                    "test_derivative_deletion.py",
                ),
            ),
            remaining_gap=(
                "Append-only database privileges and chained external audit export "
                "remain an H1 production control."
            ),
        ),
        Threat(
            threat_id="T13",
            description="Support or administrator abuses tenant access",
            risk_owner="Atlas Identity and Operations",
            inherent_severity=Severity.CRITICAL,
            residual_severity=Severity.HIGH,
            trust_boundaries=("operator/tenant resources",),
            protected_assets=("tenant content", "administrative authority"),
            primary_controls=(
                "no implicit administrator content access",
                "scoped and revocable service identities",
                "future approved break-glass workflow",
            ),
            treatment=Treatment.UNRESOLVED,
            evidence_references=(
                evidence(
                    "organization admin has no implicit content access",
                    "FIT-OWNER-006",
                    "test_ownership_lifecycle.py",
                ),
                evidence(
                    "service principal is scoped, expiring, and revocable",
                    "FIT-IDENTITY-004",
                    "test_identity_lifecycle.py",
                ),
            ),
            remaining_gap=(
                "Production break-glass incident approval, notification, and expiry "
                "are required during identity implementation."
            ),
        ),
        Threat(
            threat_id="T14",
            description="Tenant or integration exhausts shared resources or quotas",
            risk_owner="Atlas Reliability",
            inherent_severity=Severity.HIGH,
            residual_severity=Severity.HIGH,
            trust_boundaries=("client/API", "worker/provider", "tenant/shared runtime"),
            protected_assets=("service availability", "provider quotas", "fairness"),
            primary_controls=(
                "bounded AI context and agent budgets",
                "future API/job/provider quota enforcement",
            ),
            treatment=Treatment.UNRESOLVED,
            evidence_references=(
                evidence(
                    "AI context size and segment count are bounded",
                    "FIT-AI-004",
                    "test_ai_security_review.py",
                ),
                evidence(
                    "agent execution enforces a finite budget",
                    "FIT-AI-008",
                    "test_ai_security_review.py",
                ),
            ),
            remaining_gap=(
                "Production per-workspace API, job, storage, and provider quota "
                "enforcement remains required."
            ),
        ),
    )
