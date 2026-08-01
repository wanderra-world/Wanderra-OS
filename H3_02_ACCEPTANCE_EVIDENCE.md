# H3-02 Durable Execution and Scheduler Acceptance Evidence

**Owner:** Atlas Platform Engineering
**Status:** Accepted and merged through PR #28 at `915386c`
**Governing specification:** [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md#h3-02-durable-execution-and-scheduler)
**Engineering contract:** [H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md#13-h3-02-accepted-security-review-scope)

## 1. Prerequisites

- H3-01 is Accepted and merged through PR #26 at `a4602b6`.
- PR #27 opened the H3-02 gate and is merged into `origin/master` at `696b669`.
- The complete H3 architecture, implementation guide, exit definition, Architecture
  Index, and project status were reread from that merged baseline.
- The user explicitly authorized H3-02 only.
- The accepted H3-02 security review, additive migration plan, rollback rule, SLOs,
  quotas, and explicit exclusions were verified before branching.

## 2. Implemented scope

- Provider-neutral, versioned job definitions and typed command envelopes.
- Idempotent enqueue with changed-input rejection, PostgreSQL advisory transaction
  locking, explicit workspace rate/backlog quotas, and optional H3-01 resource links.
- Explicit queued, running, retry-wait, succeeded, cancelled, expired, and
  dead-lettered lifecycle states.
- Attempts, 30-second leases, 10-second heartbeat contract, lease-owner validation,
  deterministic lease-expiry recovery, deadlines, and cooperative cancellation.
- Typed transient, rate-limit, quota, permanent, authorization, validation,
  cancellation, deadline, and poison failure categories with bounded retry delays.
- Immutable dead-letter evidence and explicitly authorized replay into a new job,
  correlation chain, and idempotency key without modifying prior attempt evidence.
- One-time, interval, and IANA-timezone daily schedules with explicit skip, fire-once,
  and bounded catch-up policies, deterministic DST gap/overlap handling, and
  idempotent due-time enqueue.
- Workspace and definition pause/resume controls, workspace/definition concurrency
  limits, organization capacity input, deterministic tenant-fair round-robin order,
  and explicit backpressure.
- A generic bounded worker and typed handler conformance boundary. Handlers receive
  the caller-owned idempotency key and cannot access provider SDKs through H3-02.
- Atomic, redacted H1 audit and transactional outbox evidence for every material job,
  definition, schedule, cancellation, replay, and operator-control transition.

## 3. Explicit exclusions

No business schedule, workflow definition, document processing, knowledge, memory,
search, notification delivery, model planning, provider webhook, provider adapter,
business agent, H3-03+, broker, microservice extraction, or Phase 1 API behavior is
introduced. H3-01 resource behavior and every H0/H1/H2 contract remain unchanged.

## 4. Migration and rollback

- Revision: `0023_h3_durable_execution`.
- Parent: accepted H3-01 revision `0022_h3_resource_graph`.
- Six additive tenant tables: job definitions, instances, attempts, dead letters,
  schedules, and operator controls.
- Every table has organization/workspace/cell composite identity, workspace-consistent
  foreign keys, closed-workspace write protection, and enabled and forced RLS before
  runtime access.
- Empty upgrade, repeated upgrade, downgrade to H3-01, and re-upgrade pass.
- Populated downgrade fails closed with a reviewed-forward-fix/export instruction.
- Application and worker rollback preserve queued state; workers can be disabled
  independently without destructive schema change.

## 5. Red → Green → Refactor evidence

Red began with missing `app.jobs`, persistence, service, migration, and worker modules.
The initial domain suite failed at import and the PostgreSQL suite failed at missing
models. Green introduced only the H3-02 contracts, six-table persistence boundary,
transactional lifecycle, scheduler, and generic worker required by those tests.

Refactor added deterministic next-occurrence calculation after a failing recurrence
test exposed repeated fire-once eligibility risk. It also serialized enqueue/quota
decisions, applied the workspace concurrency ceiling, prevented paused-definition
starvation, exposed organization capacity to fair dispatch, and added the worker smoke
to the protected required workflow while all tests remained green.

## 6. Verification evidence

| Verification | Result |
|---|---|
| New H3-02 tests | 20 tests across domain, worker, PostgreSQL, migration, RLS, concurrency, recovery, scheduling, quota, and architecture boundaries |
| Complete local regression suite | 512 passed against PostgreSQL 16; one pre-existing Starlette/httpx deprecation warning |
| H3-02 PostgreSQL suite | 5 passed using isolated temporary databases |
| Architecture Fitness plus PostgreSQL | 290 passed |
| Forced RLS | Verified on all 6 tables under a non-owner, non-bypass role |
| Migration rehearsal | Empty, repeated upgrade, downgrade, and re-upgrade passed |
| Guarded populated rollback | Passed; downgrade rejected with reviewed forward-fix/export instruction |
| Concurrent claim | One live lease; competing `SKIP LOCKED` claim returned no duplicate work |
| Concurrent enqueue | Same key/input converged on one job; changed input denied |
| Crash and lease recovery | Expired attempt became immutable abandoned evidence; retry reclaimed deterministically |
| Retry/dead letter/replay | Typed retry, exhaustion/poison terminal state, and authorized new-job replay passed |
| Cancellation and pause | Immediate queued cancellation, cooperative running cancellation, workspace pause/resume passed |
| Time and DST | One-time, interval, daily-local, clock-downtime, DST gap/overlap, and next-eligibility tests passed |
| Quota and fairness | 120/minute backpressure and three-workspace deterministic round robin passed |
| Changed-scope and Architecture Ruff | Passed |
| Docker build | Passed with production image `atlas-h3-02` |
| API image smoke | Passed |
| Durable worker image smoke | Passed |
| Protected GitHub required gate | Passed for PR #28 before merge |

The reference fairness load uses three simultaneously eligible synthetic workspaces.
Each cumulative claim count differs by no more than one, and organization capacity
fails closed at 100 running jobs. Timing tests use injected aware instants; the slice
does not claim system-wide exactly-once delivery.

## 7. Security and residual risk

Negative tests or constraints cover context-free and cross-workspace access, forced
RLS, lease-owner substitution, concurrent claim, stale lease, idempotency conflict,
secret-bearing or oversized payloads, retry classification, unauthorized operation,
deadline, cancellation, replay lineage, quota backpressure, pause controls, provider
leakage, and H3-03+ scope leakage. Audit and outbox evidence contain identifiers,
state versions, and safe error codes rather than command payloads or exceptions.

No critical or high H3-02 security finding is known. The repository-wide historical
Ruff baseline contains Phase 1 formatting findings outside this slice; the protected
Architecture Ruff suite and every changed Python file pass. This pre-existing
non-safety cleanup remains outside H3-02 scope.

## 8. Compatibility and next-slice boundary

The change is additive and exposes no new HTTP API. Existing Gmail, Calendar, Drive,
Atlas chat, H0, H1, H2, and H3-01 runtime behavior remains unchanged. PR #28 merged
the accepted H3-02 implementation into `origin/master` at `915386c`, establishing
`0023_h3_durable_execution` as the accepted production migration baseline. H3-03 has
not started; its implementation is authorized only by the separately approved gate
in `README_ARCHITECTURE.md` and `H3_IMPLEMENTATION_GUIDE.md`.
