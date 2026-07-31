# H2-06 Acceptance Evidence

**Owner:** Atlas Platform Engineering  
**Specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-06-gmail-adapter-and-email-shadow-migration)  
**Status:** Implementation complete; pull-request acceptance pending  
**Date:** 31 July 2026

## Scope

H2-06 places Gmail behind the canonical email capability port with reversible
workspace routing and shadow comparison. It preserves the Phase 1 API path and does
not introduce continuous synchronization, webhooks, workers, Calendar or storage
adapters, or any H2-07+ behavior.

## Implemented evidence

- Canonical Gmail adapter for profile, list, unread, search, draft, and send.
- Opaque pagination, normalized timestamps, stable external IDs, versions, labels,
  MIME text, and namespaced provider extensions.
- Safe canonical error mapping; SDK objects and exception details cannot escape.
- Managed H2-02 credential lookup and H1 envelope decryption behind the authorized
  canonical port factory.
- Legacy, shadow, and canonical per-workspace connection routes.
- Shadow reads return the legacy result and append comparison evidence.
- Approval-gated, caller-idempotent send; shadow mode performs no provider write.
- Provider write is read back before the canonical result is returned.
- Authorized route changes with transactional audit and outbox evidence.
- Additive `0018_h2_email_capability` migration with forced RLS and guarded rollback.

## Test evidence

| Requirement | Evidence |
|---|---|
| Adapter translation and error safety | `tests/email_capability/test_h2_06_gmail_adapter.py` |
| Routing, rollback, authorization ordering, approval, replay | `tests/email_capability/test_h2_06_routing.py` |
| PostgreSQL migration, forced RLS, rollback | `tests/email_capability/test_h2_06_postgres.py` |
| SDK confinement and slice isolation | `tests/architecture/test_h2_06_gmail_scope.py` |
| Existing provider contracts | `tests/provider_capabilities/` |
| Phase 1 compatibility | Repository-wide regression and smoke suites |

## Verification record

The final local and GitHub verification results are recorded in this pull request.
Acceptance requires:

- complete pytest regression suite;
- PostgreSQL migration, forced-RLS, and rollback rehearsal;
- Architecture Fitness;
- Ruff;
- Docker build and production smoke tests;
- `H0 Required / H0 Required Gate`.

## Rollback

Set the workspace connection route to `legacy` to restore the Phase 1 execution path
without changing managed credentials. The database downgrade is allowed only while
the H2-06 tables are empty; otherwise a reviewed forward fix is required so routing
and comparison evidence cannot be silently discarded.

## Slice isolation

H2-07 has not been started. This slice contains no Calendar adapter, Drive adapter,
continuous synchronization, webhook ingestion, polling, scheduler, worker, or
provider cutover default.
