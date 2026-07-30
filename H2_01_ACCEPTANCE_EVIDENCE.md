# H2-01 Connection Foundation Acceptance Evidence

**Owner:** Atlas Core
**Slice:** H2-01 — Connection registry and lifecycle foundation
**Status:** Implemented and verified; pull-request review pending
**Date:** 30 July 2026
**Governing specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-01-connection-registry-and-lifecycle-foundation)

## Scope and exclusions

H2-01 introduces only the workspace-owned connection boundary, provider registry
metadata, versioned connection kinds and capability grants, lifecycle invariants,
context-bound persistence, H1 authorization, forced RLS, and atomic audit/outbox
evidence.

The slice contains no connection credential payload, authorization transaction,
provider mirror, external resource reference, provider client, capability execution
port, migration backfill, route cutover, or Phase 1 runtime change. H2-02 and all later
H2 slices remain unimplemented.

## Implementation evidence

- Canonical contracts and lifecycle:
  [app/connections/contracts.py](app/connections/contracts.py)
- Persistence model:
  [app/connections/models.py](app/connections/models.py)
- Context-bound repository:
  [app/connections/repository.py](app/connections/repository.py)
- Authorized transactional service:
  [app/connections/service.py](app/connections/service.py)
- Additive migration:
  [alembic/versions/0014_add_connection_foundation.py](alembic/versions/0014_add_connection_foundation.py)
- Unit evidence:
  [tests/connections/test_h2_01_contracts.py](tests/connections/test_h2_01_contracts.py)
- PostgreSQL evidence:
  [tests/connections/test_h2_01_postgres.py](tests/connections/test_h2_01_postgres.py)
- Slice-isolation fitness evidence:
  [tests/architecture/test_h2_01_connection_scope.py](tests/architecture/test_h2_01_connection_scope.py)

## Security and tenancy evidence

- Every connection stores the exact organization, workspace, and placement cell from
  the validated H1 execution context.
- A composite foreign key binds those coordinates to one canonical workspace.
- Application repositories reject missing, mismatched, and cross-workspace context.
- `connections` and `connection_capability_grants` have enabled and forced PostgreSQL
  RLS with deny-by-default workspace policies.
- A non-owner, non-superuser, non-`BYPASSRLS` role sees only the selected workspace.
- Creation and material lifecycle changes require the existing H1
  `manage_workspace` permission, so fixed workspace owners and administrators are
  allowed while viewers and ordinary members are denied.
- Stable connection identity fields are immutable; status transitions and optimistic
  version increments are enforced by both service logic and PostgreSQL.
- Revoked and closed connections expose no effective capability.
- Material state, immutable audit evidence, and transactional outbox events use one
  caller-owned transaction. Forced rollback leaves none of them committed.
- Audit and event payloads contain identifiers and lifecycle metadata only. No
  connection secret, provider authorization material, or provider payload is present.

No unresolved critical or high security finding exists for H2-01.

## Migration and rollback evidence

**Revision:** `0014_h2_connections`
**Predecessor:** `0013_h1_recovery_closure`

The migration is additive and:

- preserves populated Phase 1 user and Google integration tables;
- adds provider and capability catalogs plus workspace-owned connection tables;
- adds the workspace placement candidate key required by the composite connection
  foreign key;
- applies forced RLS before runtime use;
- attaches the accepted H1 workspace-write freeze control;
- succeeds from an empty database and a populated Phase 1 database;
- succeeds when an already-upgraded database is upgraded again;
- downgrades safely while no H2-01 state exists;
- refuses a lossy downgrade after connection, audit, or outbox state exists and
  requires a reviewed forward fix.

No Phase 1 table, credential row, OAuth callback, API contract, or provider route is
mutated.

## Reproducible verification

With `H0_TEST_DATABASE_URL` pointing to PostgreSQL 16:

```text
pytest -q tests/connections
19 passed

pytest -q tests/architecture
251 passed

pytest -q tests --ignore=tests/architecture
99 passed, 1 warning

ruff check tests/architecture app/connections \
  alembic/versions/0014_add_connection_foundation.py \
  tests/connections app/models/__init__.py app/tenancy/models.py
All checks passed

docker build --tag atlas-h2-01 .
passed

docker run --rm --entrypoint python atlas-h2-01 \
  -c "from app.main import app; from app.connections import ConnectionService; assert app.title; assert ConnectionService"
passed
```

The combined committed test inventory is 350 passing tests. The single warning is the
accepted Starlette/httpx deprecation warning and is unrelated to H2-01.

A repository-wide Ruff scan was also executed. It reports 102 pre-existing Phase 1
formatting and unused-import findings outside this slice. The mandatory Architecture
Fitness lint suite and every H2-01 changed file are clean. This low-severity baseline
observation is owned by Atlas Platform Engineering and remains scheduled for the H7
compatibility-cleanup gate; it does not weaken or bypass the protected CI check.

## Compatibility, rollback, and operational impact

- Existing Gmail, Calendar, Drive, Atlas chat, and health endpoints are unchanged.
- Phase 1 credential tables and provider service code remain authoritative.
- The new connection registry has no HTTP route and performs no external operation.
- Application rollback may use migration downgrade only before H2-01 state exists.
- Once connection evidence exists, the safe path is application rollback with the
  additive schema retained, followed by a reviewed forward fix.
- The production migration count becomes 14 after deployment.

## Pull-request gate

Dedicated pull request:
[PR #14 — Implement H2-01 connection foundation](https://github.com/wanderra-world/Wanderra-OS/pull/14)

The protected workflow completed successfully for implementation commit `2367804`:

- `H0 Required / Architecture Fitness`;
- `H0 Required / Regression Tests`;
- `H0 Required / Docker Build and Smoke`;
- `H0 Required / H0 Required Gate`.

GitHub reported 4/4 successful checks and `Ready to merge`. The documentation-only
evidence closeout remains subject to the same required gate before H2-01 completion is
declared.
