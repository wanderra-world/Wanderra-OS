# H3-07 Task Manager Acceptance Evidence

**Owner:** Atlas Platform Engineering

**Status:** Accepted and merged through PR #38

**Governing specification:** `H3_ARCHITECTURE.md` H3-07 and
`H3_IMPLEMENTATION_GUIDE.md` sections 1.37–1.44

**Migration:** `0028_h3_task_manager`, additive from accepted
`0027_h3_search_context`

## Scope delivered

- Provider-neutral canonical tasks with explicit lifecycle, priority, due constraints,
  recurrence references, source/resource identity, classification, policy version,
  optimistic version, and human provenance.
- Workspace members as assignees or watchers without implicit authorization.
- Workspace-bound dependencies with deterministic self/cycle rejection and bounded
  graph traversal.
- Classified comments, immutable completion evidence with append-only supersession,
  and external authority references that perform no provider operation.
- Deterministic active-task queries and assignee/due filtering.
- Durable reminder identities and an injected adapter to H3-02 command envelopes;
  terminal task state cancels undispatched reminders.
- Transactional audit and versioned outbox events suitable for rebuildable H3-04
  Timeline and H3-06 Search projections.

## Security, isolation, and lifecycle evidence

Every repository requires a transaction-bound canonical execution context. Every task
table includes organization, workspace, and cell identity, composite foreign keys, a
closed-workspace write trigger, and enabled and forced RLS. H1 authorization is checked
before reads or mutations; assignment, watching, dependencies, external authority, and
resource linkage do not grant access.

The explicit transition table rejects invalid and terminal-state transitions.
Mutations lock the task and require its expected optimistic version. Completion fails
closed when required evidence is absent. Accepted evidence cannot be updated or
deleted. Deletion removes tasks from active queries and cancels future reminders while
retaining audit and governed disposition evidence.

## Migration and rollback evidence

Migration `0028_h3_task_manager` adds only H3-07 task-owned tables and indexes. It does
not alter accepted H0–H3-06 tables or rewrite accepted data. Empty migration upgrade,
rollback to `0027_h3_search_context`, and re-upgrade pass. A populated downgrade fails
closed and directs operators to a reviewed forward fix or export. Application rollback
can disable new task commands while retained task state remains readable/exportable and
reminders remain cancellable.

## Verification

Recorded results through 3 August 2026:

- H3-07 acceptance tests: **9 passed**, including two real PostgreSQL tests.
- Architecture Fitness with PostgreSQL/RLS: **301 passed, 4 skipped**.
- Complete non-architecture regression suite with PostgreSQL: **272 passed**.
- Complete tracked repository result: **573 passed, 4 skipped**.
- Ruff: all changed production, migration, tests, and Architecture Fitness sources
  pass.
- Docker production image `atlas-h3-07`, application/task import smoke, and
  durable-worker smoke: **passed**.
- GitHub PR #38 run `30792292594`: Architecture Fitness, Regression Tests, Docker
  Build and Smoke, and `H0 Required / H0 Required Gate` all passed.

The four skipped tests are existing environment-gated cases. Pre-existing untracked
duplicate files whose names end in ` 2.py` are not part of Git or this pull request and
were excluded from the tracked-equivalent verification command.

## Slice isolation

PR #38 is merged into `origin/master` at `c26b35d`; revision
`0028_h3_task_manager` is the accepted production migration baseline and H3-07 is
formally Accepted. H3-07 contains no H3-08 workflow/approval behavior, H4 behavior, provider-specific
integration, connector, business-agent logic, or UI. Existing Phase 1 APIs and accepted
H0–H3-06 runtime contracts are unchanged. The H3-08 implementation gate is owned by
the approved impacts and authorization in `H3_IMPLEMENTATION_GUIDE.md`; H3-09 and
later slices remain unauthorized.
