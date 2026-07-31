# H2-07 Acceptance Evidence

**Owner:** Atlas Platform Engineering  
**Specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-07-google-calendar-adapter-and-calendar-shadow-migration)  
**Status:** Implementation complete; pull-request acceptance pending  
**Date:** 31 July 2026

## Scope

H2-07 places the existing Google Calendar behavior behind the canonical H2-05
Calendar port with reversible workspace routing and shadow comparison. It adds no
continuous synchronization, push notification, scheduler, worker, storage adapter,
new Calendar product capability, or H2-08+ behavior.

## Implemented evidence

- Canonical adapter for event list, create, update, and delete.
- Offset-preserving timed values, timezone annotations, all-day dates, recurrence,
  attendees, versions, opaque cursors, and namespaced provider extensions.
- Safe canonical error mapping with provider SDK resources, payloads, and diagnostics
  confined to the adapter.
- Authorized managed H2-02 credential lookup and H1 envelope decryption through the
  shared capability credential loader.
- Legacy, shadow, and canonical per-workspace connection routes.
- Shadow reads return the legacy result and append immutable comparison evidence.
- Approval-gated and caller-idempotent mutations; shadow mode performs no provider
  mutation.
- Mandatory update/delete version preconditions with conflict-safe failure.
- Create/update read-back and delete absence verification.
- Authorized route changes with transactional audit and outbox evidence.
- Additive `0019_h2_calendar_capability` migration with forced RLS and guarded
  rollback.

## Test evidence

| Requirement | Evidence |
|---|---|
| Calendar translation, timezone, recurrence, attendees, errors, conflicts | `tests/calendar_capability/test_h2_07_google_adapter.py` |
| Shadow routing, rollback, authorization, approval, idempotency | `tests/calendar_capability/test_h2_07_routing.py` |
| PostgreSQL migration, forced RLS, audit/outbox, rollback | `tests/calendar_capability/test_h2_07_postgres.py` |
| SDK confinement and H2-08 isolation | `tests/architecture/test_h2_07_calendar_scope.py` |
| Shared Calendar conformance | `tests/provider_capabilities/test_h2_05_conformance.py` |
| Phase 1 compatibility | Existing Calendar and repository-wide regression tests |

## Verification record

Local verification on 31 July 2026 produced:

- complete PostgreSQL-enabled suite: `455 passed`;
- Architecture Fitness: `265 passed, 4 skipped` (environment-specific live evidence);
- focused H2-07 PostgreSQL suite: `10 passed`;
- Ruff on every changed Python and migration file: passed;
- migration upgrade, repeated-upgrade, forced-RLS, empty rollback, and re-upgrade:
  passed;
- Docker production build and smoke import: passed.

Final acceptance additionally requires the pull request's
`H0 Required / H0 Required Gate` to pass.

## Migration and rollback

Revision `0019_h2_calendar_capability` additively creates only Calendar route and
shadow-comparison evidence. The default route remains `legacy`; no Phase 1 schema or
runtime route is removed. Setting a connection route to `legacy` restores the Phase 1
path without changing credentials or repeating provider effects.

Database downgrade is allowed only while the H2-07 tables are empty. Once routing or
comparison evidence exists, downgrade fails closed and requires a reviewed forward
fix so evidence cannot be silently discarded.

## Security and compatibility

Authorization precedes route lookup, managed credential decryption, and provider
access. Tenant records use composite workspace keys and forced RLS. Mutations require
approval, idempotency, audit, provider verification, and a version precondition where
the target already exists. Credentials, provider payloads, and diagnostics do not
enter audit, outbox, exceptions, or fixtures.

Phase 1 Calendar APIs and legacy credential behavior remain unchanged.

## Slice isolation

H2-08 has not been started. No Google Drive/storage adapter, file custody, change feed,
webhook, worker, polling loop, scheduling agent, or cutover default is present.
