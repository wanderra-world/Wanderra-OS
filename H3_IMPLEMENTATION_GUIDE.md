# H3 Implementation Guide

Stage-specific engineering contract for the Atlas System Intelligence Layer.

**Owner:** Atlas Platform Engineering  
**Status:** Approved for implementation through explicitly authorized slices
**Architecture:** [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md)  
**Exit contract:** [H3_EXIT_DEFINITION.md](H3_EXIT_DEFINITION.md)  
**Base engineering contract:** [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)  
**Governing decision:** [ADR-033](DECISIONS.md#adr-033-consolidate-the-remaining-reusable-platform-foundation-into-h3)

This guide owns only H3 implementation order, stage-specific constraints, compatibility,
migration, testing, evidence, and slice gates. Repository-wide engineering principles,
Definition of Ready, Definition of Done, coding standards, approval rules, and pull
request rules remain owned by `IMPLEMENTATION_GUIDE.md` and apply without duplication.

## 1. Implementation rule

H3 is eleven sequential, independently authorized vertical slices. One slice equals
one dedicated branch and pull request unless an approved risk-reduction plan divides a
slice into smaller numbered sub-slices. A slice may not absorb any capability owned by
its successor.

PR #24 formally accepted the H3 blueprint and ADR-033. This governance closeout accepts
the Architecture Index update, H3-01 security-review scope, and H3-01 migration plan
below. H3 implementation may proceed only after explicit authorization of the next
eligible slice.

### 1.1 H3-01 accepted security-review scope

H3-01 security review MUST cover direct registry insertion, unapproved resource types,
orphan or duplicate typed projections, aggregate/resource identity substitution,
cross-workspace read/write/join/traversal, invalid relationship endpoint types,
direction and cardinality violations, ownership or resource-grant escalation,
optimistic-concurrency bypass, provider external-reference substitution, deletion
integrity, audit/outbox atomicity, EAV introduction, provider leakage, and H3-02+
scope leakage. The required negative paths are owned by the H3-01 section of
`H3_ARCHITECTURE.md`, the H0 entity-integrity contract, and the base security rules.

### 1.2 H3-01 accepted migration plan

H3-01 uses one additive expand-first migration from the accepted H2 head. It adds only
the constrained Resource Graph schema required by H3-01, including workspace-inclusive
candidate keys, composite tenant foreign keys, immutable identity constraints,
optimistic versions, closed-workspace write protection, and enabled and forced RLS
before runtime writes. It performs no destructive contraction, Phase 1 provider-data
rewrite, or speculative later-slice backfill.

Empty-state downgrade MUST be proven. Once accepted Resource Graph state, audit, or
outbox evidence exists, downgrade MUST fail closed and require a reviewed forward-fix.
Provider external-reference identity fields remain immutable and are never
destructively rewritten. Migration implementation details remain subject to H3-01 Red
tests and may not broaden this accepted plan.

## 2. Recommended implementation order

| Order | Slice | Why it is next |
|---|---|---|
| 1 | H3-01 Resource Graph | Gives every later generic capability safe resource identity |
| 2 | H3-02 Durable execution/scheduler | Gives extraction, indexing, workflows, and delivery one recovery model |
| 3 | H3-03 Documents/derivation | Establishes source custody before knowledge, memory, or embeddings |
| 4 | H3-04 Knowledge/Timeline | Establishes evidence and activity semantics before memory |
| 5 | H3-05 Memory Manager | Builds governed memory on proven provenance and deletion lineage |
| 6 | H3-06 Search/Context | Indexes stable resources and derivatives with correct permissions |
| 7 | H3-07 Task Manager | Adds accountable work after generic resources/search exist |
| 8 | H3-08 Workflow Engine | Orchestrates registered commands over durable jobs and tasks |
| 9 | H3-09 Notification Center | Delivers workflow/task outcomes using the durable substrate |
| 10 | H3-10 Agent platform contracts | Adds planning/orchestration only after all safe primitives exist |
| 11 | H3-11 Formal Exit | Integrates, attacks, recovers, measures, and accepts the platform |

Reordering requires architecture review and a superseding ADR. “The model needs it” is
not a valid reason to bypass prerequisites.

## 3. Slice gate

Before each slice begins, engineering MUST verify:

1. the predecessor is explicitly accepted and merged into `origin/master`;
2. the user explicitly authorized only the requested slice;
3. the complete `H3_ARCHITECTURE.md` slice section was reread;
4. no unresolved architecture conflict or later-slice leakage exists;
5. security, tenancy, classification, custody, retention, deletion, recovery, SLO, and
   migration impacts are documented where applicable;
6. tests exist or are added first in Red state;
7. rollback versus guarded forward-fix is explicit;
8. acceptance evidence has a committed target document.

Failure stops implementation. Engineering does not invent a temporary substitute.

## 4. Architectural constraints

### 4.1 Modular-monolith boundaries

- Each H3 component owns its domain contracts, application services, persistence, and
  infrastructure adapters.
- Cross-component writes occur through commands or versioned events, never direct
  table access.
- Shared code is limited to accepted H1/H2 primitives and small behavior-free types.
- A deployable worker process may reuse the monolith package; it is not a new service
  boundary by default.

### 4.2 Tenant and authorization boundary

- Every tenant-owned primary/candidate key includes workspace identity and every
  tenant table uses forced RLS before runtime access.
- Every repository and gateway requires the canonical execution context.
- Authorization precedes database retrieval, graph traversal, index lookup, model
  egress, credential decryption, scheduling, notification, and provider access.
- Assignment, ownership, task membership, workflow participation, memory relevance,
  or agent identity never grants permission implicitly.

### 4.3 Command and event boundary

- Humans, workflows, schedules, notifications, and future agents invoke the same
  typed application commands and queries.
- Material commands use caller-owned idempotency and optimistic versions.
- State, audit, outbox, and idempotency evidence commit atomically.
- Consumers use inbox deduplication, aggregate sequence, gap handling, quarantine, and
  authorized replay.
- Scheduler, workflow, or agent code may not call another context's repository.

### 4.4 AI and content boundary

- Model output is untrusted data and cannot become a command without schema validation.
- Plans are inert, versioned proposals; prompts are not workflow definitions.
- Retrieval preserves source, classification, permission decision, and model-routing
  evidence.
- No raw prompt, secret, credential, governed document, or provider payload enters
  logs, audit, metrics, traces, exceptions, or durable fixtures.
- Unsupported classification/model combinations deny egress.

### 4.5 Data-plane separation

Operational Data, Documents, Knowledge, Memory, Timeline, and Audit use distinct models,
authority rules, retention, and APIs. A mapping between planes is explicit and records
lineage. No convenience table may merge these meanings.

### 4.6 Agent boundary

- H3-10 implements contracts and synthetic conformance agents only.
- Tool registration is administrative and versioned; agents cannot self-register.
- Tools map to application commands/queries, never SQL, repository methods, SDK calls,
  shell commands, or arbitrary Python.
- Delegation can only reduce the actor's authority.
- Approval is an execution precondition, never a permission grant.
- Every action is verified or returns an explicit uncertain outcome.

## 5. Coding rules

In addition to `IMPLEMENTATION_GUIDE.md`:

- State machines MUST be explicit, typed, versioned, and table-driven where useful.
- Clocks, ID generators, random sources, model ports, object storage, queues, search,
  and notification channels MUST be injected.
- Time-based behavior MUST use timezone-aware instants and explicit local-time/DST
  policies.
- Retry decisions MUST use typed error categories; broad exception retry is forbidden.
- Workflow and plan schemas MUST support compatibility validation before activation.
- Model, prompt, chunker, extractor, embedding, ranking, and template versions MUST be
  persisted with their outputs.
- Resource references use canonical resource IDs plus typed owner validation; generic
  JSON foreign keys are prohibited.
- Runtime loops MUST have bounded concurrency, backpressure, cancellation, deadlines,
  and shutdown behavior.
- Public contracts MUST use typed Python and deterministic serialization.
- No production TODO, mock provider, fake model, or disabled security path may remain
  at slice exit.

## 6. Compatibility guarantees

Every H3 slice MUST preserve:

- Formal H0 security and architecture fitness guarantees;
- Formal H1 identity, tenancy, authorization, execution-context, encryption, audit,
  messaging, recovery, export, closure, and deletion contracts;
- Formal H2 connection, credential, OAuth, mirror, provider-capability, routing,
  cutover, rollback, and Phase 1 API compatibility;
- existing identifiers and valid provider authorizations;
- existing Gmail, Calendar, Drive, Atlas chat, and health behavior unless a separately
  approved compatibility migration explicitly changes the route;
- forward-readable versioned events, plans, workflows, documents, indexes, and memory.

H3 MUST NOT remove H2 legacy compatibility code. Its removal remains at the explicitly
owned compatibility gate and requires production evidence, separate authorization,
and rollback protection.

## 7. Migration policy

H3 follows ADR-020 and the base migration rules.

Every schema slice MUST:

1. use additive expand-first changes;
2. support empty and populated databases at migration `0021` or the current accepted
   successor;
3. preserve all H0/H1/H2 identities and foreign keys;
4. create tenant candidate keys and forced RLS before enabling runtime writes;
5. use deterministic, idempotent, restartable backfills with counts and checksums;
6. version projections, workflows, embeddings, models, and derivatives for coexistence;
7. prove empty-state downgrade;
8. block lossy downgrade after accepted state and document a forward-fix;
9. separate application rollback, worker rollback, model rollback, index rollback,
   object-custody rollback, and schema rollback;
10. retain source evidence until derivative deletion and rollback safety are proven.

Destructive contraction is not part of an implementation slice unless explicitly
authorized after a complete compatibility window.

## 8. Testing strategy

### 8.1 Red → Green → Refactor

Each slice begins with failing acceptance, domain, PostgreSQL, and architecture tests.
The minimum production code makes them pass. Refactoring occurs only while the full
suite stays green.

### 8.2 Mandatory layers

Each slice adds applicable:

- pure domain/state-machine unit tests;
- contract and serialization compatibility tests;
- repository and service integration tests;
- real PostgreSQL composite-key, forced-RLS, concurrency, migration, rollback, and
  forward-fix tests;
- event/job/workflow replay and fault-injection tests;
- cross-workspace and privilege-escalation adversarial tests;
- retention, export, closure, recovery, and deletion-lineage tests;
- model/content prompt-injection, egress, redaction, and provenance tests;
- architecture fitness tests for layer and later-slice boundaries;
- repository-wide H0/H1/H2/H3 regression tests;
- Docker image, worker process, migration startup, and production smoke tests;
- load, soak, quality, latency, freshness, cost, and recovery tests where the slice
  introduces an SLO.

### 8.3 Determinism

Tests use injected clocks, IDs, model results, object storage, provider adapters, and
notification channels. Stochastic model quality uses versioned datasets and confidence
intervals; it is never represented as a deterministic unit-test claim.

### 8.4 Formal conformance

Shared kits MUST exist for:

- job handlers and retry classifications;
- extractors and derivative lineage;
- search/index versions;
- workflow steps and definitions;
- notification channels;
- registered tools, planners, and synthetic agents.

## 9. Evidence and documentation

Each slice produces `H3_NN_ACCEPTANCE_EVIDENCE.md` containing:

- governing scope and explicit exclusions;
- prerequisites and predecessor merge evidence;
- migration revision or schema-free rationale;
- Red/Green/Refactor test evidence;
- PostgreSQL/RLS, security, concurrency, replay, recovery, deletion, migration,
  rollback, regression, Ruff, Docker, smoke, and CI results;
- performance/quality/cost evidence where applicable;
- production behavior and compatibility impact;
- open findings with severity, owner, and expiry;
- confirmation that no later H3 slice or business agent was introduced;
- dedicated pull request and protected required-gate result.

`PROJECT_STATUS.md` records only verified implementation. `README_ARCHITECTURE.md`
changes only for navigation, ownership, or stage status. Architecture changes require
a superseding ADR before code.

## 10. Pull-request and CI contract

Every H3 pull request MUST:

- contain one authorized slice or approved smaller sub-slice;
- remain deployable and backward compatible;
- include acceptance evidence and architecture fitness coverage;
- pass the existing protected required gate plus H3-specific type, worker, migration,
  conformance, security, and quality checks introduced by the owning slice;
- wait for all checks and review before acceptance;
- be merged before the next slice begins.

No check may be made optional to merge a slice. Flaky tests are defects, not bypass
reasons.

## 11. H3 Definition of Done

A slice is complete only when the base Definition of Done and its
`H3_ARCHITECTURE.md` acceptance criteria pass, evidence is committed, the protected
pull request is accepted and merged, no critical/high finding is unresolved without
time-bounded acceptance, and no later slice or business agent has started.

Formal stage completion is governed exclusively by
`H3_EXIT_DEFINITION.md` and occurs only through H3-11.
