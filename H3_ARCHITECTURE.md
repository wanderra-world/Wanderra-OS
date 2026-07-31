# H3 System Intelligence Architecture

Canonical architecture and slice decomposition for the final reusable Atlas platform
layer before business agents.

**Owner:** Atlas Architecture Council  
**Status:** Approved; sequential production implementation permitted through explicit slice authorization
**Stage:** H3 — System Intelligence Layer  
**Architecture entry point:** [README_ARCHITECTURE.md](README_ARCHITECTURE.md)  
**Engineering contract:** [H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md)  
**Exit contract:** [H3_EXIT_DEFINITION.md](H3_EXIT_DEFINITION.md)  
**Governing decision:** [ADR-033](DECISIONS.md#adr-033-consolidate-the-remaining-reusable-platform-foundation-into-h3)

This document owns H3 vision, responsibilities, boundaries, component architecture,
slice decomposition, dependencies, and slice acceptance criteria. Domain terminology
remains owned by `DOMAIN_MODEL.md`, architecture decisions by `DECISIONS.md`, and
repository-wide engineering rules by `IMPLEMENTATION_GUIDE.md`.

PR #24 formally approved this blueprint and ADR-033. H3 production implementation is
architecturally permitted only through the sequence below. Each slice still requires
explicit user authorization after its predecessor is accepted and merged.

## 1. Vision

H3 completes the reusable Atlas platform between secure provider-neutral operations
and future business agents. It turns workspace data and provider observations into a
governed, searchable, schedulable, explainable execution environment without adding
any company-specific behavior.

At Formal H3 Exit, a future business agent can:

- discover only registered, authorized platform capabilities;
- retrieve permission-filtered context with source provenance;
- propose a versioned plan without executing it;
- create and coordinate canonical tasks and workflows;
- request approvals for risk-classified actions;
- schedule durable work and survive retries, crashes, and replay;
- notify users through provider-neutral channels;
- act only through the same application commands available to humans;
- produce complete audit, execution, cost, evidence, and outcome records.

H3 completes the reusable platform, not the product. It deliberately leaves business
policy, company workflows, industry semantics, and business agents outside Atlas Core.

## 2. Architectural position

```text
Future business agents and business modules
                  |
        registered plans, tools, workflows
                  v
        H3 System Intelligence Layer
  +-------------------------------------------+
  | resource graph | tasks | workflows       |
  | documents | knowledge | memory | search  |
  | jobs/scheduler | notifications           |
  | registry | orchestrator | planner ports  |
  | telemetry | evaluation | operator control|
  +-------------------------------------------+
                  |
       commands, queries, events, approvals
                  v
  H0/H1 secure core + H2 provider capabilities
```

H3 remains inside the modular monolith unless measured extraction criteria in
ADR-032 are met. Components are bounded contexts with explicit ports, not premature
services.

## 3. Responsibilities

H3 owns reusable platform behavior for:

1. connectable resource identity and typed projection integrity;
2. durable jobs, scheduling, leases, retries, cancellation, quarantine, and replay;
3. immutable document versions and governed derivative lineage;
4. evidence-backed knowledge and user-facing timeline projections;
5. governed long-term memory distinct from operational truth;
6. permission-aware hybrid search and context assembly;
7. canonical tasks, dependencies, assignments, and execution receipts;
8. versioned workflow definitions and durable workflow instances;
9. provider-neutral notification intents, preferences, and delivery state;
10. agent/tool registration, deterministic orchestration, and plan proposal contracts;
11. telemetry, evaluation, budgets, operator controls, recovery, and Formal H3 Exit.

## 4. Non-goals and boundaries

H3 MUST NOT implement:

- a Wanderra, Trading, finance, logistics, cleaning, property, commerce, or other
  business agent;
- business-specific workflows, dashboards, prompts, recommendations, or policies;
- autonomous goals or unconstrained self-directed execution;
- direct model, agent, or workflow access to databases or provider SDKs;
- a generic EAV operational model or unconstrained knowledge graph;
- universal event sourcing;
- cross-workspace reasoning, memory, search, or execution by default;
- a new production provider adapter;
- microservice extraction, Kafka, a graph database, or a vector database without
  measured need and a new ADR;
- an agent-authored permission grant or an approval that creates authorization;
- best-effort side effects without idempotency, preconditions, verification, or an
  explicit non-retriable classification;
- H4 or later-stage implementation.

Business agents begin only after Formal H3 Exit and separate authorization. They
compose H3 capabilities; they do not extend Atlas Core by bypassing them.

## 5. Relationship to accepted layers

### 5.1 H0

H3 inherits the approved threat model, data-plane separation, object custody,
derivative lineage, provider-conflict, AI-egress, event, recovery, and architecture
fitness contracts. H3 cannot weaken an H0 invariant.

### 5.2 H1

Every H3 object is workspace-owned and uses H1 canonical identity, membership,
authorization, execution context, forced RLS, envelope encryption, audit, outbox,
inbox, idempotency, recovery, export, retention, and closure primitives. H3 does not
create a parallel IAM, permission, approval, event, or encryption system.

### 5.3 H2

H3 consumes email, calendar, and storage only through H2 capability ports and uses H2
connections, mirrors, versions, tombstones, and external references. Synchronization
jobs may call H2 ports, but provider payloads and SDKs remain inside H2 adapters.

### 5.4 Future business agents

A business agent is an external consumer of H3 application contracts. It receives an
attenuated delegation, selects registered tools, proposes plans, and submits commands.
H1 authorizes each command at execution time; H3 applies budgets, approvals,
idempotency, and verification. Agent identity never implies workspace permission.

## 6. Canonical component boundaries

### 6.1 Resource Graph

The Resource Graph is the constrained universal entity registry from ADR-028. Only an
approved typed operational aggregate may receive resource identity. Relationships,
tags, attachments, AI notes, ownership, and resource grants attach to a canonical
resource ID, while business invariants remain in typed aggregates.

The Resource Graph is not an EAV database and does not own arbitrary fields. Graph
traversal is permission-filtered, bounded, and PostgreSQL-backed initially.

### 6.2 Durable Execution and Scheduler

The durable execution substrate owns jobs, attempts, leases, heartbeats, retry
classification, cancellation, deadlines, dead letters, authorized replay, and due-time
dispatch. A schedule states *when* an already-authorized command becomes eligible; it
does not decide *what* a business should do.

The transactional outbox remains the source of work publication. At-least-once
delivery is explicit; exactly-once external effects are never claimed.

### 6.3 Document and Derivation Service

Documents are logical records with immutable versions in approved object storage.
Extraction produces versioned chunks and derived artifacts with source, extractor or
model version, classification, custody, retention, and deletion lineage. Provider
files remain placements or sources, not durable Atlas evidence by themselves.

### 6.4 Knowledge Service and Timeline

Knowledge consists of evidence-backed claims with subject, predicate, typed value,
source span, confidence, extraction version, validity interval, and contradiction or
supersession state. It is not operational truth.

Timeline is a rebuildable user-facing projection of meaningful activity. Audit remains
immutable accountability evidence and is never replaced by Timeline.

### 6.5 Memory Manager

Memory stores governed, useful context such as preferences, decisions, summaries, and
learned working facts. Every item records provenance, classification, confidence,
scope, owner, visibility, creation method, feedback, expiry, supersession, and deletion
lineage. Memory cannot silently mutate operational aggregates or knowledge claims.

### 6.6 Search and Context Assembly

Search combines PostgreSQL full text, structured filters, graph neighborhoods, and
pgvector similarity. Authorization and visibility filters are applied before candidate
retrieval and again before response assembly. Similarity is relevance, never
permission.

Context Assembly treats retrieved content as untrusted data, preserves citations and
classification, enforces token and cost budgets, and routes only allowed information
to approved model classes.

### 6.7 Task Manager

Task Manager owns canonical tasks, status, assignees, watchers, dependencies, due
constraints, priority, source, resource links, human/agent provenance, optimistic
version, and completion evidence. A task describes accountable work; it is not a
durable execution job and does not contain provider-specific behavior.

### 6.8 Workflow and Approval Engine

The Workflow Engine owns versioned definitions, immutable instance bindings, typed
steps, conditions, waits, compensation declarations, timeouts, state transitions, and
execution receipts. Its reusable Approval Service owns immutable action digests, risk
and approver requirements, expiry, decision evidence, revocation, runtime
revalidation, and receipts. Approval never creates authorization. Definitions reference
registered application commands and queries, never Python callables, SQL, prompts, or
provider SDK methods.

Workflow determinism applies to state transitions and replay. Model-assisted planning
may propose a workflow instance, but cannot alter an accepted definition during
execution.

### 6.9 Notification Center

Notification Center accepts a canonical notification intent and applies workspace/user
preferences, classification, deduplication, quiet periods, escalation, templates, and
provider-neutral channel routing. It records delivery attempts and receipts but does
not own the business event that justified notification.

### 6.10 Agent Registry, Orchestrator, and Planner

The Agent Registry stores versioned manifests describing purpose, owner, allowed tool
classes, input/output schemas, risk ceiling, budgets, model policy, and evaluation set.
H3 registers platform contracts and synthetic test agents only; no business agent is
delivered.

The Orchestrator is deterministic application coordination: it validates context,
delegation, plan version, capability availability, budgets, approval obligations, and
command results. It does not contain business reasoning.

The Planner produces a typed, versioned, evidence-linked proposal through a model port.
A plan is inert data until validated and accepted. Plans contain registered tool
references, explicit assumptions, risk, cost estimates, preconditions, expected
outcomes, and verification steps. Free-form model output is never executable.

### 6.11 Observation, Evaluation, and Operator Control

H3 emits correlated structured logs, metrics, traces, audit references, model/tool
usage, cost, latency, quality, and outcome signals without leaking secrets or governed
content. Operators can inspect, pause, cancel, quarantine, replay, reconcile, and
disable execution at workspace, capability, workflow, agent-manifest, or global level.

Evaluation is a release gate, not a dashboard afterthought. Deterministic, adversarial,
retrieval, plan, workflow, isolation, deletion, recovery, and cost datasets are
versioned and reproducible.

## 7. Cross-cutting invariants

- Every H3 tenant row contains organization, workspace, and placement-cell context and
  is protected by forced RLS and composite tenant keys.
- Authorization occurs before retrieval, secret access, scheduling, model egress,
  provider calls, or mutations.
- State, audit, outbox, and idempotency evidence commit atomically where material state
  changes.
- External effects require approval when classified high-risk and always revalidate
  authorization, resource version, action digest, and approval at execution time.
- All content passed to a model is untrusted, minimized, classified, provenance-linked,
  and workspace-scoped.
- Operational Data, Documents, Knowledge, Memory, Timeline, and Audit remain distinct.
- Every derivative participates in retention, legal hold, export, closure, and deletion
  verification.
- Business agents may use only registered commands, queries, workflows, and tools.
- PostgreSQL remains the default system of record and coordination store until measured
  extraction criteria justify change.

## 8. H3 slice roadmap

The sequence is linear. Parallel implementation is allowed only inside a slice when
it does not weaken its acceptance gate.

| Slice | Name | Primary outcome | Complexity |
|---|---|---|---|
| H3-01 | Resource Graph foundation | Constrained connectable identity and shared resource features | High |
| H3-02 | Durable execution and scheduler | Recoverable asynchronous execution and due-time dispatch | High |
| H3-03 | Documents and governed derivation | Immutable custody, extraction, provenance, and deletion lineage | High |
| H3-04 | Knowledge Service and Timeline | Evidence-backed claims and rebuildable activity | High |
| H3-05 | Memory Manager | Governed long-term memory distinct from truth | Medium-high |
| H3-06 | Search and Context Assembly | Permission-aware hybrid retrieval and safe AI context | High |
| H3-07 | Task Manager | Canonical accountable work shared by humans and agents | Medium |
| H3-08 | Workflow and Approval Engine | Versioned, durable, approval-aware reusable workflows | Very high |
| H3-09 | Notification Center | Governed provider-neutral notification delivery | Medium |
| H3-10 | Agent platform contracts | Registry, planner proposals, orchestration, budgets, verification | Very high |
| H3-11 | Platform hardening and Formal H3 Exit | Telemetry, evaluation, recovery, conformance, exit evidence | High |

## 9. Slice specifications

### H3-01: Resource Graph foundation

**Objective:** Implement constrained universal resource identity and typed projection
integrity as the shared attachment point for reusable platform features.

**Scope:** Resource registry; approved resource types; transactional typed-projection
binding; relationships and type registry; tags; attachments; human/AI notes;
ownership; resource grants; optimistic versioning; provider external-reference links.

**Excluded:** Arbitrary EAV fields; finance or business aggregates; knowledge graph;
documents beyond attachment references; search; workflows; agents.

**Dependencies:** Formal H2 Exit; ADR-003/028; H1 tenancy/authorization; H2 external
references; approved projection-integrity contract.

**Acceptance criteria:** Every resource has one typed owner; orphan and duplicate
projections are impossible; relationship endpoints are workspace-consistent;
cross-workspace graph traversal fails; a provider email/file can link to a typed test
resource without provider leakage.

**Required tests:** Domain invariants; composite keys/RLS; relationship cardinality;
concurrency; authorization/resource grants; deletion; audit/outbox; migration and
rollback; architecture fitness against EAV and H3-02 leakage.

**Rollback:** Additive schema; safe downgrade only before accepted resource state;
otherwise retain schema and forward-fix. External references are never destructively
rewritten.

**Complexity:** High.

### H3-02: Durable execution and scheduler

**Objective:** Provide one reusable, crash-safe substrate for asynchronous work and
time-based eligibility.

**Scope:** Job definitions and instances; attempts; leases/heartbeats; retry taxonomy;
dead letters; cancellation; deadlines; idempotent enqueue; authorized replay;
recurring/one-time schedules; rate and concurrency limits; operator pause/resume.

**Excluded:** Business schedules; workflow definitions; model planning; provider
webhook product features; infrastructure extraction.

**Dependencies:** H3-01 resource references; H1 outbox/inbox/idempotency; ADR-019/029;
approved SLO and quota policies.

**Acceptance criteria:** Duplicate delivery cannot duplicate a job effect; worker
crash and lease expiry recover deterministically; cancellation and replay are audited;
schedule misfire policy is explicit; tenant fairness and isolation hold under load.

**Required tests:** Crash, lease, heartbeat, duplicate, ordering, retry exhaustion,
poison, cancellation, replay, clock skew, DST, concurrency, quota, RLS, load, recovery,
migration, rollback, and Docker worker smoke tests.

**Rollback:** Workers can be disabled independently; queued state is preserved;
downgrade is blocked once durable jobs exist and uses forward-fix/export instead.

**Complexity:** High.

### H3-03: Documents and governed derivation

**Objective:** Establish durable document custody and traceable derivative processing.

**Scope:** Logical documents; immutable versions; object-storage port; quarantine;
hash and malware/content verification; classification; extraction jobs; chunks;
derivative inventory; retention, hold, export, closure, and deletion propagation.

**Excluded:** Business document types; OCR product tuning; search ranking; knowledge
claims; memory; new storage provider.

**Dependencies:** H3-01 resources; H3-02 jobs; ADR-005/015/027; H1 encryption and
recovery; H2 storage capability/source references.

**Acceptance criteria:** Every version and derivative has immutable source lineage;
unverified content cannot enter extraction; retention/hold overrides deletion;
deletion completes across storage and metadata or records an auditable exception.

**Required tests:** Hash/custody, malware quarantine, extraction replay, lineage,
classification, object substitution, cross-workspace access, retention, legal hold,
export, restore, deletion, migration, and rollback tests.

**Rollback:** Object versions remain readable; processors can be disabled; destructive
schema rollback is prohibited after custody begins; forward-fix preserves lineage.

**Complexity:** High.

### H3-04: Knowledge Service and Timeline

**Objective:** Create evidence-backed knowledge and user-facing activity without
confusing either with operational truth or audit.

**Scope:** Typed claims; source spans; confidence; validity; contradiction;
supersession; review state; extraction provenance; timeline event projection,
rebuild/checkpoint, visibility, and resource linkage.

**Excluded:** General ontology editor; arbitrary graph database; automatic operational
updates; memory; search; recommendations.

**Dependencies:** H3-01 resources; H3-02 jobs; H3-03 source lineage; ADR-005/017/028.

**Acceptance criteria:** Claims always cite accessible evidence; contradictions remain
explicit; audit and timeline have separate schemas and retention; timeline rebuild is
deterministic; deleting a source invalidates or removes derivatives by policy.

**Required tests:** Claim identity, contradiction, supersession, confidence, source
access, projection replay, ordering, visibility, RLS, deletion lineage, migration, and
rollback tests.

**Rollback:** Projection consumers can stop and rebuild; accepted claims and evidence
are preserved; downgrade is guarded once derivatives exist.

**Complexity:** High.

### H3-05: Memory Manager

**Objective:** Provide governed long-term context with provenance, feedback, expiry,
and user control.

**Scope:** Memory items and types; source references; subject/resource links;
confidence; classification; visibility; feedback; consolidation; supersession; expiry;
pinning; human confirmation; retention/export/deletion integration.

**Excluded:** Treating memory as operational truth; unbounded conversation retention;
cross-workspace memory; search implementation; recommendations; autonomous learning.

**Dependencies:** H3-01 resources; H3-03 lineage; H3-04 knowledge distinction; H1
authorization/retention; ADR-005/018/030.

**Acceptance criteria:** Every memory is attributable and removable; expiry and
supersession are deterministic; sensitive classes obey model-routing policy; memory
cannot mutate typed aggregates; user feedback is durable and auditable.

**Required tests:** Provenance, expiry, consolidation, conflict, feedback, permission
revocation, prompt injection, egress, export, closure, deletion, RLS, migration, and
rollback tests.

**Rollback:** Memory creation can be disabled; source data remains unaffected;
forward-fix preserves feedback and deletion receipts.

**Complexity:** Medium-high.

### H3-06: Search and Context Assembly

**Objective:** Deliver permission-aware hybrid retrieval and safe, evidence-linked AI
context.

**Scope:** Search documents; full text; pgvector; structured filters; graph expansion;
ACL projection; versioned chunking/embeddings; freshness; reindex; hybrid ranking;
context minimization, citation, classification, and budgets.

**Excluded:** Business-specific ranking; answers or agents; vector authorization;
external search engine without measured need.

**Dependencies:** H3-01 through H3-05; ADR-006/012/018/030/032; approved quality,
latency, freshness, and egress thresholds.

**Acceptance criteria:** Permission filters precede retrieval; revoked access expires
within the approved SLO; results cite sources; model/chunk versions coexist during
migration; deletion propagates; relevance and latency meet measured thresholds.

**Required tests:** Lexical/vector/structured ranking, ACL attacks, stale permissions,
freshness, reindex, embedding migration, prompt injection, sensitive egress, deletion,
load, RLS, migration, and rollback tests.

**Rollback:** Lexical search remains available if vector indexing is disabled; old and
new index versions coexist; destructive index contraction waits for verification.

**Complexity:** High.

### H3-07: Task Manager

**Objective:** Provide one canonical, provider-neutral accountable-work service for
humans and future agents.

**Scope:** Tasks; lifecycle; assignees/watchers; dependencies; due constraints;
priority; recurrence reference; source; resources; comments; completion evidence;
optimistic version; commands/queries/events; external task references.

**Excluded:** Business project templates; workflow execution; job leases; calendar
event equivalence; agent-generated actions.

**Dependencies:** H3-01 resources; H3-02 scheduling; H3-04 timeline; H3-06 search; H1
authorization/audit.

**Acceptance criteria:** Lifecycle and dependency cycles fail deterministically;
assignment never grants access; overdue scheduling is idempotent; completion evidence
is immutable; external references preserve provider authority.

**Required tests:** Lifecycle, dependency graph, concurrency, assignment permission,
recurrence/DST, timeline/search projection, RLS, audit/outbox, migration, and rollback.

**Rollback:** Disable new task commands while retaining read/export; guarded downgrade
after task state; scheduled reminders are cancellable and replay-safe.

**Complexity:** Medium.

### H3-08: Workflow and Approval Engine

**Objective:** Execute reusable versioned workflows safely through registered platform
commands.

**Scope:** Definition/version registry; typed steps; conditions; waits; task/job steps;
approval service; immutable action digests; approver/risk policy; expiry/revocation;
runtime revalidation; timeouts; retries; compensation declarations; instances; tokens;
receipts; pause/cancel/replay; definition migration rules.

**Excluded:** Visual designer; business workflows; arbitrary code; dynamic SQL;
free-form prompt execution; self-modifying definitions.

**Dependencies:** H3-02 durable execution; H3-07 tasks; H1 authorization,
audit/outbox/idempotency; ADR-010/011/024/029.

**Acceptance criteria:** Instances bind immutably to a definition version; replay is
deterministic; authorization and approvals are rechecked at execution; duplicate
delivery cannot duplicate effects; compensation is explicit and never implied.

**Required tests:** State machine, definition compatibility, wait/resume, crash,
duplicate, cancellation, timeout, approval digest/expiry, changed policy/resource,
compensation, RLS, migration, rollback, and load tests.

**Rollback:** New starts can be disabled while compatible workers drain; instances
remain bound to deployable versions; incompatible rollback requires forward-fix.

**Complexity:** Very high.

### H3-09: Notification Center

**Objective:** Deliver governed notifications through reusable provider-neutral
channels.

**Scope:** Notification intents; templates/versioning; preferences; classification;
quiet periods; deduplication; escalation; digesting; channel capabilities; attempts;
receipts; bounce/failure state; in-app inbox.

**Excluded:** Marketing campaigns; business-specific copy; new provider adapters;
workflow business policy; agent conversation UI.

**Dependencies:** H3-02 jobs; H3-08 workflow events; H1 identity/authorization; H2
email capability where explicitly approved.

**Acceptance criteria:** Unauthorized or opted-out delivery fails before provider
access; duplicates collapse by intent key; secrets and sensitive content are
channel-minimized; quiet-period and escalation behavior is deterministic; receipts are
auditable.

**Required tests:** Preferences, classification, deduplication, rate limit, quiet
period/DST, retry, bounce, provider outage, redaction, cross-workspace attack, RLS,
migration, and rollback tests.

**Rollback:** Channel workers can stop while intents remain durable; in-app delivery
remains available; no accepted notification is silently discarded.

**Complexity:** Medium.

### H3-10: Agent platform contracts

**Objective:** Provide the safe registration, planning, orchestration, and tool boundary
that future business agents must use.

**Scope:** Versioned agent manifests; tool registry mapped to commands/queries;
delegation attenuation; risk metadata; budgets; model policy; typed plan proposals;
plan validation; immutable action digest; orchestration; cancellation; verification;
execution receipts; synthetic conformance agents.

**Excluded:** Business agents; autonomous goals; business prompts; direct provider or
database tools; self-registration; multi-agent social protocols; broad autonomy.

**Dependencies:** H3-01 through H3-09; ADR-009/010/011/018/024/030; approved model,
tool-risk, approval, budget, and evaluation policies.

**Acceptance criteria:** Unregistered tools cannot execute; plans are inert until
validated; delegation only attenuates permission; every command is authorized at
execution; high-risk actions require a valid action digest and approval; budgets and
emergency disable fail closed; results are verified or marked uncertain.

**Required tests:** Manifest/schema compatibility, tool confinement, delegation,
planning determinism envelope, prompt injection, changed-input/policy/resource,
approval expiry, budget/cost, cancellation, replay, provider uncertainty, data egress,
RLS, migration, and rollback tests.

**Rollback:** Disable manifests, tools, models, or orchestration independently;
in-flight operations remain inspectable/cancellable; no plan is promoted automatically.

**Complexity:** Very high.

### H3-11: Platform hardening and Formal H3 Exit

**Objective:** Prove the complete reusable platform is secure, recoverable, operable,
provider-neutral, and ready for separately authorized business agents.

**Scope:** End-to-end synthetic workspaces and agents; telemetry; SLOs; dashboards;
operator controls; chaos/fault injection; security review; backup/restore; export;
closure/deletion; performance; cost; evidence matrix; Formal H3 Exit Report.

**Excluded:** Business analytics; new functional capabilities outside
observation/evaluation/operator control; business agents; business workflows; H4 or
future roadmap work.

**Dependencies:** H3-01 through H3-10 accepted and merged.

**Acceptance criteria:** Every criterion in `H3_EXIT_DEFINITION.md` has passing
evidence; no unresolved critical/high risk lacks explicit time-bounded acceptance;
required CI is green; synthetic agents cannot bypass authorization, approvals,
budgets, commands, tenancy, or deletion; recovery and operator procedures meet SLOs.

**Required tests:** Complete H0/H1/H2/H3 regression; architecture fitness; multi-tenant
and multi-provider adversarial suites; prompt-injection/egress; workflow/job chaos;
search quality; deletion lineage; migration/rollback; backup/restore; load/soak;
Docker; production smoke; formal evidence checks.

**Rollback:** Evidence/remediation only unless an approved defect requires a guarded
fix. Formal exit is rejected if rollback, recovery, or forward-fix cannot be proven.

**Complexity:** High.

## 10. Dependency graph

```text
Formal H2 Exit
  -> H3-01 Resource Graph
  -> H3-02 Durable Execution/Scheduler
  -> H3-03 Documents/Derivation
  -> H3-04 Knowledge/Timeline
  -> H3-05 Memory
  -> H3-06 Search/Context
  -> H3-07 Tasks
  -> H3-08 Workflows
  -> H3-09 Notifications
  -> H3-10 Agent Platform Contracts
  -> H3-11 Formal H3 Exit
  -> separately authorized business agents
```

## 11. Final roadmap recommendation

Implement the sequence exactly as listed. Do not start with an orchestrator or planner:
without governed resources, durable execution, provenance, permission-aware retrieval,
tasks, and workflows, an orchestrator becomes an unsafe collection of special cases.

Do not split into microservices during H3. The correct seams are bounded-context ports,
transactional events, independent schemas/tables, and measured SLOs. Extraction is a
future operational decision, not an H3 design goal.

Do not implement business-agent examples as production code during H3. Use synthetic
conformance agents and generic fixtures so the platform proves reuse without allowing
the first business case to shape the core.
