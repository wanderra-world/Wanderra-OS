# H2 Evidence Matrix

**Owner:** Atlas Platform Engineering  
**Governing specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md)  
**Date:** 31 July 2026

This matrix is the formal trace from every H2 slice to its committed acceptance
evidence. Test paths are reproducible evidence; pull-request checks provide the
merge-blocking execution record.

| Slice | Accepted deliverable | Primary evidence | Security, migration, and rollback evidence |
|---|---|---|---|
| H2-01 | Workspace connection registry and lifecycle | [H2_01_ACCEPTANCE_EVIDENCE.md](H2_01_ACCEPTANCE_EVIDENCE.md), `tests/connections/` | Forced RLS, context isolation, additive revision `0014`, guarded downgrade |
| H2-02 | Managed credential custody and migration inventory | [H2_02_ACCEPTANCE_EVIDENCE.md](H2_02_ACCEPTANCE_EVIDENCE.md), `tests/connection_credentials/` | Envelope encryption, redaction, forced RLS, revision `0015`, recovery runbook |
| H2-03 | OAuth authorization transactions | [H2_03_ACCEPTANCE_EVIDENCE.md](H2_03_ACCEPTANCE_EVIDENCE.md), `tests/oauth_transactions/` | PKCE/state binding, replay and expiry rejection, revision `0016` |
| H2-04 | Provider mirrors and external references | [H2_04_ACCEPTANCE_EVIDENCE.md](H2_04_ACCEPTANCE_EVIDENCE.md), `tests/provider_mirrors/` | Cross-workspace rejection, conflict evidence, revision `0017` |
| H2-05 | Provider-neutral capability contracts and SDK boundary | [H2_05_ACCEPTANCE_EVIDENCE.md](H2_05_ACCEPTANCE_EVIDENCE.md), `tests/provider_capabilities/` | Deterministic second-provider kit; provider SDK confinement; schema-free |
| H2-06 | Canonical Gmail adapter and reversible email routing | [H2_06_ACCEPTANCE_EVIDENCE.md](H2_06_ACCEPTANCE_EVIDENCE.md), `tests/email_capability/` | Approval, replay, shadow mismatch, forced RLS, revision `0018` |
| H2-07 | Canonical Google Calendar adapter and routing | [H2_07_ACCEPTANCE_EVIDENCE.md](H2_07_ACCEPTANCE_EVIDENCE.md), `tests/calendar_capability/` | Approval, version conflicts, rollback, forced RLS, revision `0019` |
| H2-08 | Canonical Google Drive adapter and routing | [H2_08_ACCEPTANCE_EVIDENCE.md](H2_08_ACCEPTANCE_EVIDENCE.md), `tests/storage_capability/` | Approval, version conflicts, transient content, forced RLS, revision `0020` |
| H2-09 | Connection cutover and compatibility stabilization | [H2_09_ACCEPTANCE_EVIDENCE.md](H2_09_ACCEPTANCE_EVIDENCE.md), `tests/connection_cutover/` | Idempotent backfill, thresholded cutover, recovery/export/closure, revision `0021` |
| H2-10 | Synthetic multi-provider validation and Formal H2 Exit | [H2_10_ACCEPTANCE_EVIDENCE.md](H2_10_ACCEPTANCE_EVIDENCE.md), `tests/acceptance/test_h2_10_multi_provider.py` | [H2_SECURITY_REVIEW.md](H2_SECURITY_REVIEW.md), full migration/rollback, Docker, smoke, and CI records |

## Cross-cutting exit criteria

| Criterion | Trace |
|---|---|
| Gmail, Calendar, and Drive use neutral ports | H2-05 contracts; H2-06 through H2-08 adapter and routing tests; H2-10 integrated canonical-output test |
| A non-Google provider satisfies the same contracts | Shared H2-05 conformance kit plus two independent H2-10 deterministic mock connections |
| Legacy, shadow, canonical, and rollback behavior | H2-06 through H2-09 routing, mismatch, threshold, cutover, and fault-injection tests |
| Approval, idempotency, and version preconditions | Capability service tests and H2-10 adversarial replay/stale-version tests |
| Workspace and connection isolation | Every H2 PostgreSQL suite, forced-RLS architecture checks, and synthetic connection isolation test |
| Credential and OAuth safety | H2-02/H2-03 negative paths, encryption/redaction checks, recovery exercises |
| Migration, recovery, export, closure, and deletion | Revisions `0014`–`0021`, migration rehearsals, H2-09 manifests and closure tests |
| Architectural integrity and backward compatibility | Architecture Fitness, repository-wide regression, Docker build, production smoke, protected required gate |

No evidence item authorizes H3. Formal H2 Exit authorizes consideration only.
