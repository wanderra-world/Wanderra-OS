# H2-10 Acceptance Evidence

**Owner:** Atlas Platform Engineering  
**Specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-10-synthetic-multi-provider-conformance-and-formal-h2-exit)  
**Status:** Implemented and locally verified; pull-request gate pending  
**Date:** 31 July 2026

## Scope and exclusions

H2-10 is an evidence-only conformance and formal-exit slice. It adds integrated
synthetic multi-provider and adversarial acceptance tests, a complete H2 evidence
matrix, a formal security review, and the Formal H2 Exit Report. It introduces no
production capability, schema, provider integration, H3 universal entity, worker,
document, search, memory, or agent functionality. H3 has not been started.

## Multi-provider and canonical behavior evidence

- Gmail, Google Calendar, and Google Drive adapters are exercised through the H2-05
  canonical ports and return canonical DTOs without provider payload leakage.
- Two independent deterministic mock-provider instances prove that identical
  capability contracts do not depend on Google identity or payload shapes and that
  connection state cannot cross synthetic workspace boundaries.
- Mock email, calendar, and storage capabilities remain covered by the shared H2-05
  conformance suite.
- Adversarial H2-10 tests prove changed-input replay and stale-version mutation fail
  closed with canonical conflict errors.
- H2-06 through H2-09 tests remain the authoritative integrated evidence for legacy,
  shadow, canonical, mismatch, cutover, and rollback behavior.

## Security, recovery, and compatibility evidence

[H2_SECURITY_REVIEW.md](H2_SECURITY_REVIEW.md) traces credential revocation, OAuth
replay, workspace attacks, approval, idempotency, conflicts, redaction, SDK
confinement, recovery, export, closure, and deletion boundaries to committed tests.
No unresolved critical or high finding remains.

[H2_EVIDENCE_MATRIX.md](H2_EVIDENCE_MATRIX.md) traces H2-01 through H2-10 and every
formal exit criterion. Phase 1 APIs remain backward compatible; no provider route,
credential, schema, or production runtime behavior changes in H2-10.

## Migration and rollback evidence

H2-10 is schema-free. Production migration head remains
`0021_h2_connection_cutover`; the repository has 21 production migrations in total.
The complete migration suite rehearses upgrade, repeat upgrade, guarded
downgrade/forward-fix, forced RLS, populated Phase 1 compatibility, and rollback.
Application rollback removes only the H2-10 tests and evidence documents; it cannot
affect database or provider state.

## Reproducible verification

Local verification used an isolated PostgreSQL 16 database:

```text
pytest -q tests/architecture
275 passed

pytest -q tests --ignore=tests/architecture
204 passed, 1 accepted Starlette deprecation warning

ruff check tests/architecture
All checks passed

ruff check tests/acceptance/test_h2_10_multi_provider.py \
  tests/architecture/test_h2_10_formal_exit.py
All checks passed

alembic upgrade head
passed from an empty PostgreSQL database through 0021

alembic downgrade 0020_h2_storage_capability && alembic upgrade head
passed

docker build --tag atlas-h2-10 .
passed

docker run --rm --entrypoint python atlas-h2-10 -c "production import smoke"
passed
```

The complete committed inventory is **479 passing tests**, including **5 new H2-10
tests**. PostgreSQL/RLS, replay, conflict, migration, rollback, recovery, export,
closure, compatibility, routing, and conformance tests are included in those suites.

A repository-wide advisory `ruff check .` continues to report the accepted 102
pre-existing Phase 1 style findings outside H2-10. The merge-blocking Ruff scope
(`tests/architecture`) and every H2-10 Python file are clean; H2-10 changes none of
the legacy files. The `H0 Required / H0 Required Gate` result remains pending until
the dedicated pull request runs on GitHub.

## Findings and slice isolation

No known critical or high finding is open. H2-10 adds no migration. H3 has not been
started. Formal acceptance remains contingent on the dedicated pull request passing
all mandatory checks and being reviewed under the protected branch policy.
