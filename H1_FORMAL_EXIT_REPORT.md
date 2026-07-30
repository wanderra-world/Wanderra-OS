# Formal H1 Exit Report

**Owner:** Atlas Engineering  
**Decision date:** 30 July 2026  
**Decision:** Accepted  
**Governing specification:** [H1_PLATFORM_SPEC.md](H1_PLATFORM_SPEC.md)  
**Engineering gate:** [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#h1)

## Decision

**Formal H1 Exit is accepted. Phase H1 is closed.**

H1-01 through H1-10 are merged into `master`. Every H1 exit criterion is supported by
committed automated evidence, the complete PostgreSQL-backed regression suite is
green, the production Docker image passes its smoke test, and the protected-branch
GitHub gate passed for the H1-10 merge.

This decision does not start H2. H2 requires separate authorization and must follow
its approved prerequisites and implementation sequence.

## Accepted slice baseline

| Slice | Accepted outcome | Merge evidence |
|---|---|---|
| H1-01 | Organization, workspace, ownership, placement, audit, outbox, and forced-RLS foundation | PR #1 |
| H1-02 | Canonical users and immutable issuer/subject identity links | PR #3 |
| H1-03 | Revocable sessions, invitations, recovery, strong-authentication state, and lifecycle evidence | PR #4 |
| H1-04 | Workspace membership lifecycle and versioned fixed roles | PR #5 |
| H1-05 | Deterministic deny-first authorization boundary | PR #6 |
| H1-06 | Request, actor, tenant, transaction, and repository execution context | PR #7 |
| H1-07 | Managed per-record envelope encryption and migration tooling | PR #8 |
| H1-08 | Immutable audit, transactional outbox/inbox, idempotency, sequencing, quarantine, and replay controls | PR #9 |
| H1-09 | Encrypted recovery, isolated restore, H1 export, retention, closure, and deletion evidence | PR #10 |
| H1-10 | Synthetic two-tenant vertical slice and integrated security acceptance | PR #11 |

## Exit-criterion verification

| Criterion | Evidence | Result |
|---|---|---|
| Synthetic tenant isolation | Application-context adversarial tests and forced PostgreSQL RLS probes across two organizations and workspaces | Passed |
| Revocation | Session revocation followed by authentication and authorization denial | Passed |
| Deterministic authorization | Fixed-role allow and workspace-mismatch deny decisions | Passed |
| Explicit repository context | Context-bound repository rejection and transaction-local tenant propagation | Passed |
| Audit integrity | Immutable chained audit records and verification function | Passed |
| Event safety | Atomic outbox/inbox, duplicate suppression, optimistic concurrency, gap quarantine, and authorized replay | Passed |
| Encryption | Tenant-bound managed envelope encryption, rotation, corruption, outage, and revocation paths | Passed |
| Recovery | Encrypted backup, key recovery, isolated restore, row-count and digest equivalence, RPO and RTO evidence | Passed |
| Closure and deletion | Write freeze, immediate access revocation, legal-hold precedence, eligible H1 erasure, and immutable receipt | Passed |
| Migration safety | Additive migrations through `0013_h1_recovery_closure`, downgrade or guarded forward-fix rehearsals | Passed |
| Phase 1 compatibility | Gmail, Calendar, Drive, memory, and API regression coverage | Passed |
| Security review | No unresolved critical or high finding and no risk waiver for either class | Passed |

## Verification record

- Complete local suite: **329 passed**, with one non-blocking existing
  Starlette/httpx deprecation warning.
- PostgreSQL, forced RLS, migration, rollback, recovery, concurrency, and replay
  verification: **passed**.
- Architecture Fitness and acceptance Ruff scope: **passed**.
- Production Docker build and application smoke test: **passed**.
- Pull request #11 GitHub checks:
  - Architecture Fitness: **passed**;
  - Regression Tests: **passed**;
  - Docker Build and Smoke: **passed**;
  - H0 Required Gate: **passed**.
- `master` branch protection:
  - pull request required;
  - required status checks enabled;
  - `H0 Required Gate` required from GitHub Actions;
  - branch must be current before merge;
  - conversations must be resolved;
  - linear history required;
  - administrator bypass disabled.
- Production migration count: **13**.
- Production schema head: `0013_h1_recovery_closure`.

## Production invariants

- Phase 1 API behavior and Google integrations remain backward compatible.
- H1 is provider-neutral; no provider migration or Google-specific business logic was
  introduced into Atlas Core.
- Tenant-owned H1 persistence uses explicit workspace context and forced RLS.
- Security-relevant state changes retain audit and transactional event evidence.
- H1 closure explicitly excludes provider-owned data; reconciliation remains an H2
  responsibility.
- No H2, universal entity, memory-engine, search, or agent implementation was started
  as part of Formal H1 Exit.

## Residual limitations

Accepted limitations are scoped to later approved stages and do not block H1:

- Phase 1 routes do not yet use H1 authentication and authorization paths; H2 owns
  migration and cutover.
- Provider-owned data reconciliation is not part of H1 closure.
- The existing Starlette/httpx deprecation warning is non-blocking.
- Repository-wide legacy Phase 1 Ruff debt remains outside the merge-blocking
  architecture and acceptance lint scope.

## Final acceptance

There are no remaining H1 exit blockers. No unresolved critical or high security
finding requires risk acceptance.

**Phase H1 status: Accepted.**
