# H3-08 Workflow and Approval Engine Acceptance Evidence

**Owner:** Atlas Platform Engineering

**Status:** Implemented on dedicated H3-08 branch; pending review and merge

**Governing specification:** `H3_ARCHITECTURE.md` H3-08 and
`H3_IMPLEMENTATION_GUIDE.md` sections 1.45–1.52

**Migration:** `0029_h3_workflow_approval`, additive from accepted
`0028_h3_task_manager`

## Scope delivered

- Immutable, versioned provider-neutral workflow definitions with typed registered
  command, query, task, wait, and approval references.
- Deterministic workflow transitions, immutable instance-version bindings, optimistic
  concurrency, caller-owned idempotency identities, wait tokens, transition receipts,
  explicit terminal and uncertain outcomes, and explicit compensation declarations.
- Approval requests and immutable decisions bound to canonical SHA-256 action digests,
  risk, policy version, expiry, revocation, quorum, and runtime authorization checks.
- Execution-context-bound repository and service boundaries with atomic audit and
  transactional outbox evidence.
- Eight new workspace-owned PostgreSQL tables with composite tenant keys, forced RLS,
  additive migration, empty-state downgrade, and populated-state forward-fix guard.

## Explicit exclusions

No notification delivery, agent or planner behavior, business workflow, UI, provider
or connector implementation, external integration, arbitrary code, SQL, prompt
execution, H3-09+, or H4 behavior is included.

## TDD and verification evidence

- Red: contract and architecture tests initially failed because `app.workflows` and
  revision `0029_h3_workflow_approval` did not exist.
- Green: deterministic contracts, persistence, repository, service, migration, and
  audit/outbox integration made the focused suite pass.
- PostgreSQL: real pgvector/PostgreSQL 16 rehearsal validates all eight tables, enabled
  and forced RLS, empty downgrade/re-upgrade, and guarded populated downgrade.
- Rollback: application rollback can disable starts while state remains inspectable;
  destructive populated downgrade fails with the required reviewed-forward-fix rule.
- Architecture Fitness: provider-neutral boundary and H3-09+ exclusion are executable.

## Verification results

- New H3-08 tests: **9 passed** (5 deterministic contract tests, 2 Architecture
  Fitness tests, and 2 real PostgreSQL/RLS/migration tests).
- Complete staged repository suite: **586 passed**, with the existing single
  Starlette/httpx deprecation warning.
- Complete tracked Architecture Fitness: **303 passed, 4 skipped**.
- Ruff for H3-08 production, migration, test, model-registry, and Architecture Fitness
  scope: **passed**.
- Alembic: single head `0029_h3_workflow_approval`; upgrade, empty downgrade/re-upgrade,
  forced RLS, and populated downgrade refusal passed on pgvector/PostgreSQL 16.
- Production Docker image `atlas-h3-08`: **built successfully**.
- Production application import smoke and durable worker smoke: **passed**.
- Protected GitHub results are recorded on the dedicated pull request before merge.

## Compatibility and security

The migration is additive and rewrites no accepted H0–H3-07 data. Existing Phase 1,
H1, H2, and H3 contracts remain unchanged. Workflow participation and approval never
grant permission; canonical authorization is revalidated at execution. No reusable
credential, provider payload, governed content, or raw prompt is persisted or logged.

## Slice isolation

H3-09, H3-10, H3-11, H4, UI, providers, connectors, external integrations, and
business agents remain unauthorized and unimplemented.
