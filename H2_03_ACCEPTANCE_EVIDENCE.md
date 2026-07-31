# H2-03 OAuth Transaction Acceptance Evidence

**Owner:** Atlas Core  
**Slice:** H2-03 — OAuth transaction and incremental authorization boundary  
**Status:** Accepted and merged
**Date:** 31 July 2026  
**Governing specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-03-oauth-transaction-and-incremental-authorization-boundary)

## Scope and exclusions

H2-03 adds only the canonical workspace-owned, single-use OAuth transaction,
provider-neutral protocol dispatch and credential-custody handoff contracts, encrypted
state/PKCE custody, deterministic scope policy, and callback lifecycle evidence.

Phase 1 routes, provider clients, credentials, registered callback URL, and legacy
state tables remain unchanged. This slice adds no provider resource mirror, external
reference, capability operation, adapter cutover, worker, HTTP API, Microsoft
provider, or H2-04 and later functionality.

## Implementation evidence

- Provider-neutral lifecycle and security contracts:
  [app/oauth_transactions/contracts.py](app/oauth_transactions/contracts.py)
- Secret-free tenant persistence:
  [app/oauth_transactions/models.py](app/oauth_transactions/models.py)
- Execution-context-bound repository and concurrency controls:
  [app/oauth_transactions/repository.py](app/oauth_transactions/repository.py)
- Transactional start and callback completion:
  [app/oauth_transactions/service.py](app/oauth_transactions/service.py)
- Additive migration:
  [alembic/versions/0016_add_oauth_transactions.py](alembic/versions/0016_add_oauth_transactions.py)
- Unit, redaction, PostgreSQL, RLS, migration, replay, and concurrency evidence:
  [tests/oauth_transactions](tests/oauth_transactions)
- Slice-isolation evidence:
  [tests/architecture/test_h2_03_oauth_scope.py](tests/architecture/test_h2_03_oauth_scope.py)

## Security, scope, and concurrency evidence

- A 256-bit random state is returned only to the initiating caller. PostgreSQL stores
  its SHA-256 digest and a non-secret workspace routing coordinate.
- Raw state and PKCE verifier are encrypted together through the accepted H1
  AES-256-GCM managed-envelope service. They are never written to OAuth metadata,
  audit, outbox, exception, or representation output.
- Encrypted-envelope authenticated data binds workspace, connection, transaction
  identity, provider, and authorization purpose. A PostgreSQL trigger independently
  verifies this binding.
- Callback completion locks the state row. The first valid consumer performs one
  protocol exchange and one H2-02 handoff; concurrent or later consumers fail closed.
- Pending is the only mutable lifecycle state. PostgreSQL rejects replay or mutation
  of a terminal transaction.
- Actor, session, membership, authorization decision, workspace, provider,
  connection, issuer, redirect URI, purpose, and expiry are bound.
- Returned scopes are normalized deterministically. Supersets are accepted only when
  all required scopes exist and no scope falls outside the allowlist.
- Forced RLS and the accepted closed-workspace write trigger protect every row.

## Migration and rollback evidence

**Revision:** `0016_h2_oauth_transactions`  
**Predecessor:** `0015_h2_credentials`

The migration is additive, leaves every Phase 1 table and runtime path intact, enables
and forces RLS before use, and installs database lifecycle and envelope-context
invariants. Empty upgrade, repeated upgrade, empty rollback, and re-upgrade are
rehearsed. Downgrade refuses to discard transaction evidence and requires a reviewed
forward fix.

## Verification results

```text
Focused H2-03 Ruff
All checks passed

Focused H2-03 tests
25 passed

Architecture Fitness
258 passed

Complete non-architecture regression suite
132 passed, 1 accepted deprecation warning

Production Docker build
atlas-h2-03 built successfully

Production image smoke
FastAPI application, H2-03 service, and ORM model imported successfully
```

The complete local inventory is **390 passing tests**. The merge-blocking Ruff scope
and every H2-03 changed Python file pass. A diagnostic repository-wide Ruff run also
reports the accepted legacy Phase 1 formatting baseline outside the required workflow;
H2-03 adds no new violation.

## Compatibility and open findings

- Existing Gmail, Calendar, and Drive OAuth tests remain part of the mandatory
  repository regression gate.
- The canonical callback coordinator is a provider-neutral service contract and does
  not probe legacy provider state tables.
- Phase 1 callback routing remains operational and unchanged until an approved adapter
  cutover slice.
- Production migration count becomes 16 after deployment.

No unresolved H2-03 critical or high finding is known. H2-04 has not started.

## Pull-request gate

Dedicated pull request:
[PR #16 — Implement H2-03 OAuth transaction boundary](https://github.com/wanderra-world/Wanderra-OS/pull/16)

The protected workflow passed for the implementation commit:

- `H0 Required / Architecture Fitness` — passed;
- `H0 Required / Regression Tests` — passed;
- `H0 Required / Docker Build and Smoke` — passed;
- `H0 Required / H0 Required Gate` — passed.

PR #16 was accepted and merged into `master` as commit `c5a8344`. H2-04 began only
after that accepted baseline.
