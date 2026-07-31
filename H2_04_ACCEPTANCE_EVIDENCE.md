# H2-04 Provider Mirror Acceptance Evidence

**Owner:** Atlas Core  
**Slice:** H2-04 — Provider mirror and external-reference foundation  
**Status:** Accepted and merged

**Date:** 31 July 2026  
**Governing specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-04-provider-mirror-and-external-reference-foundation)

## Scope and exclusions

H2-04 adds only provider-resource mirror identity, immutable external references,
authority metadata, provider versions/ETags/timestamps, normalized hashes, tombstones,
conflict evidence, comparison decisions, explicit user-resolution evidence, and
idempotent persistence.

It adds no provider SDK or provider invocation, capability port, adapter, continuous
synchronization, webhook, poller, scheduler, worker, automatic conflict resolution,
raw-payload blob custody, universal entity, typed H3 aggregate, API, or H2-05 and later
functionality. Phase 1 Gmail, Calendar, Drive, and every accepted H1/H2 runtime path
remain unchanged.

## Implementation evidence

- Provider-neutral authority and comparison contracts:
  [app/provider_mirrors/contracts.py](app/provider_mirrors/contracts.py)
- Tenant-owned mirror, external-reference, conflict, and comparison models:
  [app/provider_mirrors/models.py](app/provider_mirrors/models.py)
- Execution-context-bound repository:
  [app/provider_mirrors/repository.py](app/provider_mirrors/repository.py)
- Transactional observation and decision service:
  [app/provider_mirrors/service.py](app/provider_mirrors/service.py)
- Additive migration:
  [alembic/versions/0017_add_provider_mirrors.py](alembic/versions/0017_add_provider_mirrors.py)
- Unit and PostgreSQL acceptance tests:
  [tests/provider_mirrors](tests/provider_mirrors)
- Slice-isolation fitness tests:
  [tests/architecture/test_h2_04_mirror_scope.py](tests/architecture/test_h2_04_mirror_scope.py)

## Security, authority, and tenancy evidence

- Identity is unique by workspace, connection, resource type, and external ID.
- Repository operations require the accepted H1 execution context and
  `manage_workspace` authorization.
- Every tenant-owned table has enabled and forced RLS plus closed-workspace write
  protection.
- Composite foreign keys and database triggers prevent cross-workspace or mismatched
  mirror/reference joins.
- Provider and external-reference identity coordinates are immutable.
- Provider-authoritative changes apply; Atlas-authoritative, user-resolved, and
  mergeable ambiguity produces conflict evidence.
- Reused provider versions with changed normalized meaning conflict.
- Stale outbound preconditions require refresh and never invoke or blindly retry a
  provider operation.
- Provider deletion creates a tombstone without erasing external linkage, comparison,
  conflict, audit, or outbox evidence.
- Raw provider payloads are not stored. An optional raw-payload reference is accepted
  only with a paired approved custody owner.
- Audit and outbox payloads contain identifiers and lifecycle metadata only.

## Idempotency and conflict evidence

- Advisory transaction locks serialize each workspace/idempotency key.
- Exact observation and decision replay returns the recorded outcome.
- Changed input under an existing key fails closed.
- Conflicts are explicit durable records with reason, competing hashes, provider
  version, detection time, and one-way open-to-resolved lifecycle.
- Resolution binds actor, resolution choice/hash, time, and idempotency evidence.
- Resolution changes authority to `user_resolved`; no automatic merge occurs.

## Migration and rollback evidence

**Revision:** `0017_h2_provider_mirrors`  
**Predecessor:** `0016_h2_oauth_transactions`

The migration adds four empty H2-04 tables, enables and forces RLS before runtime use,
installs workspace write protection, and enforces identity, custody-reference,
optimistic-version, conflict-transition, and comparison-immutability invariants.
Empty upgrade, repeated upgrade, empty downgrade, and re-upgrade are rehearsed.
Downgrade refuses to discard mirror evidence and requires a reviewed forward fix.
No Phase 1 or previously accepted H2 table is altered.

## Verification results

```text
Focused H2-04 Ruff
All checks passed

Focused H2-04 tests
14 passed

Architecture Fitness
260 passed

Complete non-architecture regression suite
144 passed, 1 accepted deprecation warning

Production Docker build
atlas-h2-04 built successfully

Production image smoke
FastAPI application, H2-04 service, and ORM model imported successfully
```

The complete local inventory is **404 passing tests**.

## Protected GitHub verification

**Pull request:** [#17](https://github.com/wanderra-world/Wanderra-OS/pull/17)

**Workflow run:** [H0 Required 30593838349](https://github.com/wanderra-world/Wanderra-OS/actions/runs/30593838349)

- Architecture Fitness: passed.
- Regression Tests: passed.
- Docker Build and Smoke: passed.
- H0 Required Gate: passed.

Pull request #17 was accepted and merged as commit `254e516`. H2-04 satisfies the
mandatory protected-branch checks.

## Compatibility and findings

- Production migration count becomes 17 after deployment.
- Production APIs and provider behavior remain unchanged.
- H2-04 is synchronization-state persistence only; durable processing remains H4.
- No live-provider authorization or end-to-end provider call is applicable.
- No unresolved H2-04 critical or high finding is known.
- H2-05 has not started.
