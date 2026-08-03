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

### 1.3 H3-02 accepted security-review scope

H3-02 security review MUST cover forged or context-free enqueue, workspace or resource
substitution, cross-workspace claim/heartbeat/cancel/replay, lease-owner substitution,
concurrent claim, stale heartbeat, retry-category escalation, deadline bypass,
idempotency-key reuse with a different command digest, unauthorized dead-letter replay,
schedule activation or pause without operator authority, quota bypass, starvation,
payload or exception leakage, audit/outbox non-atomicity, and H3-03+ scope leakage.
Job payloads remain typed command envelopes, are classified at enqueue, and MUST NOT
contain credentials, provider tokens, arbitrary executable code, or raw provider SDK
payloads. Replay is a new authorized execution referencing immutable prior evidence; it
never edits or silently reopens the original attempt.

### 1.4 H3-02 accepted migration plan

H3-02 uses one additive expand-first migration from accepted revision
`0022_h3_resource_graph`. It adds only the durable-execution schema required by the
H3-02 scope: job definitions and instances, attempts, leases, dead letters, schedules,
and operator controls. Every tenant-owned key includes organization, workspace, and
cell identity; composite foreign keys preserve that identity; enabled and forced RLS
exist before runtime writes. The migration performs no H3-01 rewrite and no provider,
workflow, document, model, search, notification, or business-agent backfill.

Empty-state downgrade MUST be proven. After durable execution, attempt, schedule,
dead-letter, audit, or outbox evidence exists, schema downgrade MUST fail closed and
require worker disablement plus a reviewed forward-fix or export. Application and
worker rollback preserve queued state and MUST NOT discard or re-run accepted work.

### 1.5 H3-02 approved SLO and quota policy

This section is the single normative owner of H3-02 service objectives and quotas.
Values are versioned configuration with the following safe defaults; deployments may
lower limits, but raising them requires measured capacity evidence and architecture
review. Tests use an injected monotonic clock and a reference load of at least three
active workspaces so results are deterministic and tenant fairness is observable.

| Control | Approved default and required behavior |
|---|---|
| Eligible-job dispatch | At reference load, 95% start within 5 seconds and 99% within 30 seconds of eligibility while capacity is available. |
| Lease and heartbeat | Default lease is 30 seconds; heartbeat interval is 10 seconds and MUST be no greater than one third of the lease. Expired work becomes reclaimable within 5 seconds without overlapping a valid lease. |
| Recovery | After a worker stops heartbeating, eligible retry or terminal classification occurs within 35 seconds. No successful effect is repeated without the command's idempotency or version precondition. |
| Retry budget | At most 5 attempts. Typed retry delays are 1, 5, 30, and 120 seconds, capped by the job deadline. Permanent, authorization, validation, cancellation, and expired-deadline failures never retry. |
| Workspace concurrency | At most 20 running jobs per workspace and 100 per organization by default. The lower applicable limit wins. |
| Enqueue rate and backlog | At most 120 accepted enqueues per workspace per rolling minute and 10,000 non-terminal jobs per workspace. Excess work receives explicit backpressure and is never silently dropped. |
| Claim fairness | Claims use deterministic workspace round-robin ordering. While equally eligible workspaces remain below their quotas, their cumulative claim counts differ by no more than one. |
| Scheduler catch-up | Every schedule declares `skip`, `fire_once`, or bounded `catch_up`. Catch-up is limited to 10 occurrences per evaluation and is also subject to enqueue and concurrency quotas. |
| Dead letters and replay | Retry exhaustion or poison classification creates operator-visible dead-letter evidence within the terminal transaction. Replay requires explicit authorization, reason, correlation ID, and a new idempotency key. |
| Pause and cancellation | Workspace or definition pause prevents new claims within 5 seconds. Cancellation prevents an unstarted job immediately and is observed by a cooperative running handler by its next heartbeat, no later than 10 seconds. |
| Availability objective | The durable execution control plane targets 99.9% monthly availability, excluding an authorized emergency pause; correctness, tenant isolation, and auditability take precedence over dispatch latency. |

The implementation MUST expose quota and SLO outcomes without tenant-sensitive
payloads, document the reference-load environment in H3-02 evidence, and fail the
slice gate if dispatch, recovery, isolation, fairness, or backpressure cannot be
reproduced. These targets authorize H3-02 implementation only; later slices own their
own content, search, model, notification, and agent objectives.

### 1.6 H3-03 accepted security-review scope

H3-03 security review MUST cover context-free or cross-workspace document access,
object or version substitution, content-hash mismatch, mutable source evidence,
unverified-content promotion, quarantine bypass, malware-result forgery, MIME/content
confusion, classification downgrade, unauthorized signed-object access, extractor or
chunk replay with changed inputs, derivative-lineage gaps, legal-hold or retention
bypass, incomplete deletion, secret or governed-content leakage in logs and events,
and H3-04+ scope leakage. The review inherits the accepted P0.7 custody controls in
`H0_FOUNDATION_SPEC.md` and ADR-005, ADR-015, and ADR-027; it does not create a second
security model.

### 1.7 H3-03 accepted classification impact

Every logical document, immutable version, extraction request, chunk, and derivative
records its effective classification and the policy version that produced it.
Classification may remain unchanged or become more restrictive during derivation; a
downgrade requires the existing authorized governance path and durable evidence.
Unclassified, unsupported, or policy-incompatible content fails closed before
extraction, model egress, export, or signed-object access. Provider metadata is an
untrusted classification input and never the final authority.

### 1.8 H3-03 accepted custody impact

H3-03 implements the existing H0 object-custody contract through a provider-neutral,
injected object-storage port. A logical document owns immutable, content-addressed
versions. Promotion from quarantine requires tenant placement, expected hash, MIME and
content validation, malware/content verification, classification, encryption and key
metadata, and durable custody evidence. H2 files are source placements or external
references only; H3-03 does not add or bypass a storage-provider adapter. Object access
is authorized before issuing a short-lived reference, and accepted versions are never
overwritten in place.

### 1.9 H3-03 accepted retention impact

The precedence defined by `H0_FOUNDATION_SPEC.md` remains authoritative: legal hold,
statutory or contractual minimum, approved security hold, workspace policy, user
deletion, then expiry. Document versions and every registered derivative participate
in the same workspace governance decision. Legal hold and minimum retention block
physical deletion without making content generally readable. Export and workspace
closure use the accepted H1 governance and recovery boundaries and preserve custody
and lineage evidence.

### 1.10 H3-03 accepted deletion impact

Deletion is a durable, idempotent propagation process over the source version, object,
chunks, and derivative inventory. It either verifies removal at every currently owned
target or records an explicit auditable exception with target, reason, and retry or
operator disposition. Legal hold or retention produces a governed blocked outcome,
not a false success. H3-03 does not delete H2 provider files unless an already
authorized H2 capability is explicitly invoked; provider-source disposition remains
visible in the deletion evidence. Later knowledge, memory, search, and timeline
derivatives are outside this slice.

### 1.11 H3-03 accepted recovery impact

Backups, restore manifests, workspace export, and closure inventories MUST include H3
document metadata, immutable version identity, object custody references, derivative
inventory, classification and policy versions, holds, retention state, and deletion
exceptions. Restore verifies tenant placement and content hashes before making an
object readable or extraction-eligible. Extraction jobs are replayed through H3-02
using the original source digest and versioned processor contract; changed input is a
new derivative execution. Recovery never silently resurrects a deleted or quarantined
object.

### 1.12 H3-03 accepted migration plan

H3-03 uses one additive expand-first migration from accepted revision
`0023_h3_durable_execution`. It adds only the document and governed-derivation schema
defined by `H3_ARCHITECTURE.md`: logical documents, immutable versions, custody and
verification metadata, chunks, derivative inventory, and retention/deletion state.
Every tenant-owned key includes organization, workspace, and cell identity; composite
foreign keys preserve it; enabled and forced RLS exist before runtime writes. The
migration performs no H3-01 or H3-02 rewrite, provider-file migration, knowledge,
memory, search, workflow, notification, agent, or business-data backfill.

Empty-state downgrade MUST be proven. Once accepted custody, version, derivative,
hold, deletion, audit, or outbox evidence exists, destructive schema downgrade MUST
fail closed. Application processors and extraction workers may be disabled while
objects and metadata remain readable through the authorized custody boundary; repair
uses a reviewed forward-fix or export and MUST preserve immutable lineage.

### 1.13 H3-04 accepted security-review scope

H3-04 security review MUST cover context-free or cross-workspace claim and timeline
access, resource or source-version substitution, source-span and content-hash mismatch,
inaccessible or deleted evidence, forged extraction provenance or confidence,
predicate/value type confusion, claim-identity replay with changed inputs,
contradiction or supersession erasure, validity-interval manipulation, automatic
operational-data mutation, timeline visibility bypass, audit/timeline conflation,
event-order or checkpoint gaps, non-deterministic projection replay, deletion-lineage
bypass, governed-content leakage in logs or events, and H3-05+ scope leakage. The
review inherits H1 authorization/audit/messaging, H3-01 resource identity, H3-02
durable execution, H3-03 source custody, ADR-005, ADR-017, and ADR-028 rather than
creating parallel controls.

### 1.14 H3-04 accepted classification impact

Every claim, evidence link, source span, contradiction, review record, and timeline
projection records its effective classification and the policy version that produced
it. A derivative is never less restrictive than any source contributing to it.
Provider metadata, extractor output, confidence, and timeline visibility are untrusted
inputs and cannot lower classification or grant access. Authorization and source
visibility are revalidated before claim or timeline retrieval.

### 1.15 H3-04 accepted custody impact

Knowledge references immutable H3-03 document versions and bounded source spans with
content-hash lineage; it does not overwrite, replace, or become the custodian of source
documents. Claims derived from operational resources use typed H3-01 references and
explicit provenance. Timeline stores a rebuildable projection and source references,
not copies of audit evidence. Missing, substituted, quarantined, or inaccessible
source custody fails closed and leaves an explicit invalid or unavailable derivative
state rather than fabricating evidence.

### 1.16 H3-04 accepted retention impact

Knowledge, Timeline, Documents, Operational Data, and Audit keep distinct retention
and authority rules. Legal hold and minimum retention continue to take precedence.
Knowledge and timeline records participate in workspace export, closure, and source
disposition without extending the retention of source content by accident. Audit
retention is unchanged; timeline retention cannot delete or rewrite audit evidence.

### 1.17 H3-04 accepted deletion impact

Source deletion or loss of access triggers a durable, idempotent H3-02 propagation
that invalidates or removes dependent claims according to the governing policy and
rebuilds affected timeline projections. Contradiction, supersession, and deletion
receipts remain sufficient to explain the outcome without retaining governed source
content beyond policy. Partial propagation records an auditable exception and retry or
operator disposition; it never reports false completion.

### 1.18 H3-04 accepted recovery impact

Backups, restore manifests, workspace export, and closure inventories include claim
identity, typed value and predicate versions, evidence/source references, confidence,
validity, contradiction, supersession, review, classification, timeline checkpoint,
and deletion state. Restore verifies tenant placement and accessible source lineage
before making a claim active. Timeline is rebuilt deterministically from authorized,
versioned source events; checkpoints accelerate replay but are not independent truth.

### 1.19 H3-04 accepted migration plan

H3-04 uses one additive expand-first migration from accepted revision
`0024_h3_document_custody`. It adds only the Knowledge Service and Timeline schema
defined by `H3_ARCHITECTURE.md`: typed claims, source spans and provenance,
contradiction/supersession/review state, timeline projections, and rebuild checkpoints.
Every tenant-owned key includes organization, workspace, and cell identity; composite
foreign keys preserve it; enabled and forced RLS exist before runtime writes. The
migration performs no rewrite of accepted H3-01 through H3-03 state and no memory,
search, task, workflow, notification, agent, provider, or business-data backfill.

Empty-state downgrade MUST be proven. Once accepted claim, contradiction, review,
timeline, checkpoint, audit, or outbox evidence exists, destructive schema downgrade
MUST fail closed. Projection consumers may be disabled and rebuilt while accepted
claims and evidence remain readable through their authorized boundaries; repair uses
a reviewed forward-fix or export and preserves provenance.

### 1.20 H3-04 implementation authorization

H3-04 is Accepted and merged through PR #32 at `38c326d`, its protected required
checks passed, and revision `0025_h3_knowledge_timeline` is the accepted production
migration baseline.

### 1.21 H3-05 accepted security-review scope

H3-05 security review MUST cover context-free or cross-workspace memory access,
forged or inaccessible provenance, source/resource substitution, memory-type or scope
confusion, confidence manipulation, expiry bypass, pinning abuse, consolidation replay
with changed inputs, supersession or conflict erasure, feedback forgery, confirmation
bypass, permission-revocation lag, prompt-injection persistence, model-egress policy
bypass, governed-content leakage in logs or events, deletion-lineage gaps, and H3-06+
scope leakage. The review inherits H1 authorization, retention, audit, messaging, and
AI-egress controls plus H3-01 resource identity, H3-03 source custody, H3-04 knowledge
distinction, ADR-005, ADR-018, and ADR-030 rather than creating parallel controls.

### 1.22 H3-05 accepted classification impact

Every memory item, source reference, consolidation input, supersession, feedback,
confirmation, and deletion state records effective classification and policy version.
A memory is never less restrictive than any source contributing to it. User or model
labels, summaries, confidence, visibility, and feedback are untrusted inputs and
cannot lower classification or grant access. Authorization, visibility, source access,
and approved model-routing policy are revalidated before retrieval or model egress.

### 1.23 H3-05 accepted custody impact

Memory references immutable H3-03 document versions, H3-04 claims, or typed H3-01
resources through explicit provenance; it does not become the custodian of operational
truth, documents, or knowledge evidence. Consolidated memory preserves the complete
input lineage and the policy/version that produced it. Missing, substituted,
quarantined, revoked, or inaccessible source custody fails closed and leaves an
explicit unavailable or invalid memory state rather than fabricating context.

### 1.24 H3-05 accepted retention impact

Memory has explicit expiry, pinning, confirmation, retention, and supersession state
separate from Operational Data, Documents, Knowledge, Timeline, and Audit. Legal hold
and minimum retention take precedence; pinning cannot override deletion, legal,
workspace-closure, or source-access policy. Unbounded conversation retention and
implicit expiry extension are prohibited. Memory and feedback participate in
workspace export and closure without extending source-content retention by accident.

### 1.25 H3-05 accepted deletion impact

Source deletion, permission revocation, expiry, workspace closure, or loss of source
access triggers deterministic, idempotent memory invalidation or removal according to
policy. Consolidated and superseding items remain linked to every contributing source
so disposition propagates transitively. Feedback and deletion receipts retain only
the minimized evidence required to explain the outcome. Partial propagation records
an auditable exception and retry or operator disposition; it never reports false
completion.

### 1.26 H3-05 accepted recovery impact

Backups, restore manifests, workspace export, and closure inventories include memory
identity and type, source/resource references, confidence, classification, visibility,
feedback, confirmation, consolidation, expiry, pinning, supersession, and deletion
state. Restore verifies tenant placement, policy version, source accessibility, and
disposition before making memory available. Deterministic lifecycle evaluation is
replayed from persisted timestamps and provenance; caches or future search indexes are
not independent truth.

### 1.27 H3-05 accepted migration plan

H3-05 uses one additive expand-first migration from accepted revision
`0025_h3_knowledge_timeline`. It adds only the Memory Manager schema defined by
`H3_ARCHITECTURE.md`: governed memory items, provenance/source links, durable
feedback, consolidation/supersession lineage, confirmation, pinning, expiry, and
disposition state. Every tenant-owned key includes organization, workspace, and cell
identity; composite foreign keys preserve it; enabled and forced RLS exist before
runtime writes. The migration performs no rewrite of accepted H3-01 through H3-04
state and no search, embedding, task, workflow, notification, agent, provider, or
business-data backfill.

Empty-state downgrade MUST be proven. Once accepted memory, feedback, confirmation,
consolidation, deletion, audit, or outbox evidence exists, destructive schema
downgrade MUST fail closed. Memory creation and consolidation may be disabled while
accepted records remain readable through authorized boundaries; repair uses a reviewed
forward-fix or export and preserves provenance, feedback, and deletion receipts.

### 1.28 H3-05 implementation authorization

H3-05 is Accepted and merged through PR #34 at `670205d`, its protected required
checks passed, and revision `0026_h3_governed_memory` is the accepted production
migration baseline.

### 1.29 H3-06 accepted security-review scope

H3-06 security review MUST cover context-free or cross-workspace index access,
workspace/organization/cell substitution, ACL projection forgery or lag, authorization
after candidate retrieval, vector-similarity authorization, source or citation
substitution, stale source/version access, deleted-content resurrection, embedding or
chunk-version confusion, query and filter injection, unbounded graph expansion,
ranking manipulation, prompt-injection persistence, context-budget bypass,
classification or model-route downgrade, governed-content leakage in logs/events,
reindex replay with changed inputs, and H3-07+ scope leakage. The review inherits H1
authorization/execution context, H3-01 resource identity, H3-03 custody, H3-04
knowledge provenance, H3-05 memory governance, and ADR-006/012/018/030/032.

### 1.30 H3-06 accepted classification and model-egress impact

Every search document, chunk reference, embedding, ACL projection, result, citation,
and assembled context records effective classification and policy/model/index version.
Classification is at least as restrictive as every contributing source. Authorization,
visibility, current source custody, and model-route policy are applied before candidate
retrieval and revalidated before response assembly or model egress. Restricted content
may use only the approved private model route. Unsupported or mixed-classification
routes fail closed; similarity, ranking, or graph proximity never grants access.

### 1.31 H3-06 accepted custody and lineage impact

Search is a rebuildable derivative plane, never source custody or operational truth.
Every indexed field, chunk, and embedding references an immutable source identity,
source version/digest, producing chunker/embedding/index version, classification, and
policy version. H3-06 does not copy provider payloads or bypass H3-03 document custody,
H3-04 claim evidence, or H3-05 memory source validation. Missing, changed, quarantined,
revoked, or inaccessible lineage makes the candidate unavailable and queues governed
reconciliation instead of fabricating context.

### 1.32 H3-06 accepted retention and deletion impact

Search documents, ACL projections, chunks, embeddings, index generations, caches, and
rebuild artifacts inherit source retention, hold, export, closure, and deletion
decisions without extending source retention. Permission revocation and source
disposition deny retrieval immediately through authoritative pre-retrieval filtering,
even while derivative cleanup is pending. Cleanup is deterministic and idempotent;
partial deletion records an auditable exception and retry/operator disposition, never
a false completion. Old index generations remain inaccessible after cutover and are
removed only after verified rollback and retention windows.

### 1.33 H3-06 accepted recovery and reindex impact

Search indexes are disposable projections rebuilt from authorized source inventories.
Recovery manifests include source/version counts, index/chunker/embedding/model
versions, ACL projection versions, checksums, cutover state, and deletion exceptions,
but not reusable credentials or unnecessary governed content. Reindex uses H3-02
durable jobs with deterministic inputs, bounded concurrency, resumable checkpoints,
tenant fairness, and replay protection. Lexical retrieval remains the safe rollback
path while vector indexing or a new generation is disabled or rebuilding.

### 1.34 H3-06 approved quality, latency, freshness, and egress policy

This section is the single normative owner of H3-06 acceptance thresholds. Tests use
a versioned, deterministic provider-neutral corpus containing at least 100 judged
queries across at least three workspaces, including exact identifiers, lexical,
semantic, structured-filter, graph-neighborhood, stale-permission, deleted-source,
prompt-injection, and mixed-classification cases. Raising exposure or budget limits
requires measured evidence and architecture review.

| Control | Approved threshold and required behavior |
|---|---|
| Tenant and permission safety | Zero tolerated unauthorized candidates or context fragments. Authoritative workspace, visibility, and source-access predicates run before candidate retrieval and again before assembly. |
| Citation and lineage | 100% of returned results and context fragments identify an accessible source and immutable source/version plus index policy/version. Missing lineage fails closed. |
| Exact and structured retrieval | Recall@10 is at least 0.95 for judged exact-identifier and structured-filter queries. Exact matches cannot be displaced solely by vector similarity. |
| Hybrid relevance | NDCG@10 is at least 0.75 on the complete judged corpus and may not regress by more than 0.02 versus the accepted lexical baseline without review. |
| Query latency | At a documented reference load of 100,000 searchable records and three active workspaces, warm p95 is at most 500 ms and p99 at most 1 second, excluding model and external-provider latency. Correctness takes precedence over latency. |
| Index freshness | 95% of accepted source changes become searchable within 60 seconds and 99% within 5 minutes while the durable job SLO is available. Lag is observable and never weakens authoritative access checks. |
| Revocation and deletion | Revoked or disposed content is non-retrievable in the next transaction through authoritative filtering; derivative removal completes within 60 seconds for 95% and 5 minutes for 99%, or records an explicit exception. |
| Context budget | Assembly is deterministic and capped by caller policy, with a safe default of 8,192 input tokens and 20 source fragments. Truncation preserves citation boundaries and never silently drops classification metadata. |
| Model egress | Restricted content requires the private route; unsupported routes deny. The evaluation corpus tolerates zero prompt-injection instruction execution, cross-workspace disclosure, citation loss, or classification downgrade. |

### 1.35 H3-06 accepted migration plan

H3-06 uses additive expand-first migration from accepted revision
`0026_h3_governed_memory`. It adds only provider-neutral search documents, ACL
projections, versioned chunks/embeddings/index generations, freshness/checkpoint, and
reconciliation state required by `H3_ARCHITECTURE.md`. Tenant keys include
organization, workspace, and cell identity; composite foreign keys preserve source
identity; enabled and forced RLS exist before runtime access. PostgreSQL full text and
pgvector remain the approved platform under ADR-006/032. The migration performs no
rewrite of accepted H3-01 through H3-05 state and no task, workflow, notification,
agent, provider, connector, business-data, H3-07+, or H4 backfill.

Empty-state downgrade MUST be proven. Once accepted search, embedding, ACL, index,
reconciliation, audit, or outbox evidence exists, destructive schema downgrade MUST
fail closed. Application rollback disables the affected index generation and retains
authorized lexical retrieval; old/new versions coexist until parity, deletion,
freshness, quality, and rollback evidence permits reviewed contraction.

### 1.36 H3-06 implementation authorization

H3-06 is Accepted and merged through PR #36 at `a34322e`, its protected required
checks passed, and revision `0027_h3_search_context` is the accepted production
migration baseline.

### 1.37 H3-07 accepted security-review scope

H3-07 security review MUST cover context-free or cross-workspace task access,
workspace/organization/cell substitution, assignment or watcher membership being
mistaken for authorization, unauthorized lifecycle transitions, optimistic-version
bypass, idempotency-key reuse with changed input, dependency-cycle and graph-amplification
attacks, recurrence or overdue-reminder amplification, reminder replay after task
completion or cancellation, mutable or substituted completion evidence, comment and
external-reference injection, provider-authority confusion, sensitive task content in
logs/events, deletion or closure resurrection, and H3-08+ scope leakage. The review
inherits H1 authorization/execution context/audit/outbox, H3-01 resource identity,
H3-02 scheduling, H3-04 timeline, H3-06 search isolation, and ADR-005/010/011/018/030.

### 1.38 H3-07 accepted classification and authorization impact

Every task, source reference, comment, completion-evidence reference, external
reference, search projection, timeline event, reminder command, audit event, and
outbox event records or inherits effective classification and policy version.
Classification is at least as restrictive as every contributing source. Canonical H1
authorization executes before every command and query and is revalidated when a
scheduled reminder becomes eligible. Assignment, watching, ownership, dependency,
source linkage, or external authority never grants access. H3-07 performs no model
egress and stores no credentials or provider payloads.

### 1.39 H3-07 accepted operational custody and lineage impact

The Task Manager owns provider-neutral operational task truth. Every task has one
canonical H3-01 resource identity and may reference, but never absorb, H3-03 document
custody, H3-04 evidence/timeline records, or H3-06 derivative search state. Source and
completion evidence use immutable resource/version/digest references. External task
references identify provider-owned authority without treating Atlas as authoritative
for provider state and without invoking provider APIs. Timeline and search remain
rebuildable projections of accepted task events rather than alternate task truth.

### 1.40 H3-07 accepted retention and deletion impact

Tasks, participants, dependencies, comments, completion evidence, external references,
reminder state, timeline entries, search projections, audit, and outbox evidence obey
workspace retention, hold, export, closure, and deletion policy. Completion evidence is
immutable; correction appends superseding evidence rather than rewriting history.
Task deletion is a governed lifecycle transition that immediately removes the task
from active queries and cancels future reminders while preserving required audit,
retention, and deletion receipts. Derivative cleanup is idempotent and cannot extend
source retention or falsely report completion after a partial failure.

### 1.41 H3-07 accepted recovery and scheduling impact

Recovery exports canonical task state, versions, participants, dependency edges,
comments, evidence references, external references, reminder identities, and checksums
without reusable credentials or provider payloads. Timeline and search projections are
rebuilt from canonical tasks and versioned events. Overdue and recurrence scheduling
uses H3-02 durable jobs with deterministic inputs, caller-owned idempotency, bounded
expansion, explicit timezone/DST policy, cancellation on terminal state, and replay
protection. Restore reconciles scheduled identities before dispatch so recovery cannot
duplicate reminders or reopen terminal tasks.

### 1.42 H3-07 approved lifecycle, concurrency, and scheduling policy

This section is the single normative owner of H3-07 acceptance controls.

| Control | Approved requirement |
|---|---|
| Authorization and isolation | Zero tolerated cross-workspace records, unauthorized commands, or unauthorized task/query projections. Assignment and watching never grant permission. |
| Lifecycle | Only the versioned canonical transition table may change status. Invalid or terminal-state transitions fail closed and produce no task event. |
| Concurrency and replay | Every material command requires expected version and caller-owned idempotency; changed-input replay fails and concurrent winners are deterministic. |
| Dependencies | Self-dependencies and directed cycles are rejected before persistence. Traversal and mutation remain workspace-bound and bounded. |
| Completion evidence | Every completed task has immutable evidence or an explicit evidence-not-required policy decision; accepted evidence coverage is 100%. |
| Scheduling | Overdue and recurrence identities are deterministic across DST and recovery. Duplicate reminders or reminders after completion/cancellation are not tolerated. |
| External authority | External references are unique within their authority boundary and never imply provider mutation, synchronization, access, or ownership. |
| Projection freshness | Timeline/search changes use transactional outbox evidence; lag is observable and never weakens canonical authorization or task truth. |

### 1.43 H3-07 accepted migration plan

H3-07 uses additive expand-first migration from accepted revision
`0027_h3_search_context`. It adds only provider-neutral canonical task state,
participants, dependencies, comments, completion evidence, external references, and
reminder/reconciliation state required by `H3_ARCHITECTURE.md`. Tenant keys include
organization, workspace, and cell identity; composite foreign keys preserve task,
resource, actor, source, and evidence boundaries; enabled and forced RLS exist before
runtime access. The migration performs no rewrite of accepted H3-01 through H3-06
state and no workflow, approval, notification, agent, UI, provider, connector,
business-data, H3-08+, or H4 backfill.

Empty-state downgrade MUST be proven. Once accepted task, participant, dependency,
comment, completion, external-reference, reminder, audit, or outbox evidence exists,
destructive schema downgrade MUST fail closed. Application rollback disables new task
commands while retaining authorized read/export and cancellable durable reminders;
populated rollback requires a reviewed forward fix or export.

### 1.44 H3-07 implementation authorization

H3-07 is Accepted and merged through PR #38 at `c26b35d`, its protected required
checks passed, and revision `0028_h3_task_manager` is the accepted production
migration baseline.

### 1.45 H3-08 accepted security-review scope

H3-08 security review MUST cover context-free or cross-workspace definition and
instance access, definition/version substitution, mutable running definitions,
unregistered command or query references, arbitrary code/SQL/prompt execution,
condition or token injection, duplicate or reordered step delivery, wait/resume race,
timeout/cancellation/replay confusion, forged approval requests or decisions,
action-digest substitution, self-approval, approval expiry/revocation bypass, changed
actor/policy/permission/resource preconditions, compensation being mistaken for
rollback, secret or governed-content leakage in state/events, operator-control bypass,
and H3-09+ scope leakage. The review inherits H1 authorization, execution context,
idempotency, audit/outbox/inbox, H3-02 durable execution, H3-07 tasks, and
ADR-010/011/024/029 rather than creating parallel controls.

### 1.46 H3-08 accepted classification and authorization impact

Every definition version, instance, step input/output reference, token, wait,
approval request/decision, action digest, receipt, compensation declaration, audit
event, and outbox event records or inherits effective classification and policy
version. Classification is never less restrictive than contributing inputs.
Canonical H1 authorization is checked before definition administration, instance
start/query/mutation, approval decisions, resume/replay, and every registered command
execution. Workflow participation, task assignment, step ownership, or approval never
grants permission. Approval is an additional execution precondition, not authority.

### 1.47 H3-08 accepted custody and lineage impact

The Workflow Engine owns versioned definitions, immutable instance bindings, state
transitions, tokens, and receipts; it does not own task truth, job execution evidence,
documents, knowledge, memory, provider state, or authorization. Definitions reference
versioned registered application command/query identifiers and typed schemas, never
Python callables, repository methods, SDK operations, SQL, or free-form prompts.
Every transition and receipt identifies definition version, prior state/version,
input digest, actor, correlation/causation, command result, and applicable approval.

### 1.48 H3-08 accepted retention and deletion impact

Definitions, instances, tokens, waits, approvals, decisions, receipts, and
compensation evidence participate in workspace retention, legal hold, export, closure,
and deletion policy. Running instances bind immutably to retained definition versions.
Deletion or closure prevents new starts and cancels eligible work while preserving the
minimal evidence required for accountability and disposition. Approval revocation and
expiry remain visible; no cleanup may turn a denied, expired, cancelled, or uncertain
outcome into success.

### 1.49 H3-08 accepted recovery and execution impact

Recovery inventories definition versions, instance state/version, step tokens, waits,
deadlines, idempotency identities, approvals, receipts, compensations, and checksums
without reusable credentials or provider payloads. H3-02 jobs resume only from the
last committed deterministic transition. Restore reconciles job/token/receipt identity
before dispatch so accepted effects are not duplicated. New starts can be disabled
while compatible workers drain; incompatible versions remain deployable or require a
reviewed forward fix.

### 1.50 H3-08 approved determinism, approval, and execution policy

This section is the single normative owner of H3-08 acceptance controls.

| Control | Approved requirement |
|---|---|
| Definition integrity | Activated versions are immutable; running instances remain bound to one version. Compatibility is validated before activation. |
| Deterministic execution | Persisted state, typed input, definition version, and recorded outcomes fully determine the next transition. Duplicate/reordered delivery cannot duplicate a transition or effect. |
| Command confinement | Steps invoke only versioned registered application commands/queries through typed ports. Arbitrary code, SQL, prompts, repositories, SDKs, and provider payloads are prohibited. |
| Authorization and approval | Authorization is revalidated at execution. High-risk steps also require an unexpired, unrevoked approval bound to the immutable normalized action digest; approval never grants permission. |
| Concurrency and replay | Every material transition uses expected state version and caller-owned idempotency. Replay creates new authorized execution evidence and never edits history. |
| Waits and deadlines | Wait/resume, timeout, cancellation, and H3-02 job identity are deterministic and race-safe. Terminal instances cannot resume. |
| Compensation | Compensation is explicit, separately authorized, idempotent, and receipted. It never implies that an external effect was rolled back. |
| Failure outcome | Success, failure, cancellation, compensation failure, and uncertain external outcome remain explicit, auditable, and operator-visible. |

### 1.51 H3-08 accepted migration plan

H3-08 uses additive expand-first migration from accepted revision
`0028_h3_task_manager`. It adds only provider-neutral workflow definition/version,
instance, step/token/wait, approval request/decision, action-digest, receipt,
compensation, and reconciliation state required by `H3_ARCHITECTURE.md`. Tenant keys
include organization, workspace, and cell identity; composite foreign keys preserve
definition, instance, task, job, actor, approval, and receipt boundaries; enabled and
forced RLS exist before runtime access. The migration performs no rewrite of accepted
H3-01 through H3-07 state and no notification, agent, UI, provider, connector,
business-data, H3-09+, or H4 backfill.

Empty-state downgrade MUST be proven. Once accepted definition, instance, token, wait,
approval, receipt, compensation, audit, or outbox evidence exists, destructive schema
downgrade MUST fail closed. Application rollback disables new starts while compatible
workers drain and accepted instances remain inspectable, cancellable, and exportable;
populated rollback requires a reviewed forward fix or export.

### 1.52 H3-08 implementation authorization

H3-08 is Accepted and merged through PR #40 at `386d365`; its protected checks passed
and revision `0029_h3_workflow_approval` is the accepted production migration
baseline. Its acceptance evidence is `H3_08_ACCEPTANCE_EVIDENCE.md`. The next gate is
owned exclusively by the H3-09 governance sections below.

### 1.53 H3-09 accepted security-review scope

H3-09 security review MUST cover context-free or cross-workspace intent, template,
preference, inbox, attempt, and receipt access; identity or destination substitution;
preference and opt-out bypass; classification downgrade; template injection; secrets
or governed-content leakage; duplicate delivery; quiet-period, digest, escalation, and
rate-limit bypass; stale authorization; forged receipts; bounce or provider-outage
confusion; replay after cancellation, deletion, or workspace closure; channel routing
outside registered provider-neutral capabilities; and H3-10+ scope leakage. The review
inherits H1 authorization, execution context, audit/outbox/inbox/idempotency, H3-02
durable execution, H3-08 workflow evidence, and ADR-010/011/018/024/029.

### 1.54 H3-09 accepted classification and authorization impact

Every notification intent, rendered artifact, preference decision, digest membership,
delivery attempt, receipt, failure, inbox entry, audit event, and outbox event records
or inherits effective classification and policy version. Classification is never less
restrictive than contributing inputs. Canonical H1 authorization is checked before
intent creation/query/mutation, preference changes, rendering, scheduling, channel
routing, delivery, replay, and receipt access. A destination, workflow participant,
task assignment, inbox entry, or prior delivery never grants permission.

### 1.55 H3-09 accepted custody and lineage impact

Notification Center owns provider-neutral intents, template versions, preferences,
delivery decisions, attempts, receipts, and in-app inbox state. It does not own the
business event, workflow truth, task truth, provider credentials, provider payloads,
or authorization. Every intent cites its source event or aggregate, template version,
classification, actor, correlation/causation, normalized destination reference, and
deduplication identity. Templates are inert typed data and cannot contain executable
code, SQL, prompts, repository calls, SDK operations, or provider-specific payloads.

### 1.56 H3-09 accepted retention and deletion impact

Intents, rendered artifacts, preferences, attempts, receipts, failures, and inbox state
participate in workspace retention, legal hold, export, closure, and deletion policy.
Rendered content is minimized and may expire before immutable delivery evidence.
Deletion or closure prevents new delivery and cancels eligible queued attempts while
preserving the minimum evidence required for accountability and disposition. No
cleanup may turn an opted-out, suppressed, failed, bounced, cancelled, or uncertain
delivery into success.

### 1.57 H3-09 accepted recovery and delivery impact

Recovery inventories intent identity, source lineage, template version, preference and
policy decisions, schedule/job identity, deduplication key, attempt state, receipt,
failure classification, and checksums without reusable credentials or provider
payloads. H3-02 jobs resume only from committed notification state. Restore reconciles
intent/attempt/receipt identity before delivery so accepted effects are not duplicated.
Channel workers can be disabled while intents remain inspectable, cancellable,
exportable, and deliverable to the canonical in-app inbox.

### 1.58 H3-09 approved determinism and delivery policy

This section is the single normative owner of H3-09 acceptance controls.

| Control | Approved requirement |
|---|---|
| Intent identity | Caller-owned intent and deduplication keys bind normalized source, recipient, template version, classification, and purpose. Key reuse with changed input fails closed. |
| Authorization and preference | Current authorization, membership, destination eligibility, opt-out, and preference policy are checked before scheduling and again before delivery. |
| Classification and minimization | Channel capability must support the effective classification. Rendered content is minimized, redacted, and never contains credentials, raw provider payloads, or unnecessary governed content. |
| Quiet periods and digesting | Timezone, DST, quiet-period, digest-window, escalation, and misfire behavior are explicit and deterministic under an injected clock. |
| Concurrency and retry | Attempts use H3-02 jobs, optimistic state, inbox/outbox deduplication, typed retry categories, bounded rate/concurrency, and terminal bounce/failure states. |
| Provider neutrality | Delivery uses a registered provider-neutral channel port. H3-09 adds no provider adapter, connector, SDK dependency, or provider-name business branch. |
| Receipts and uncertainty | Attempts and receipts are immutable evidence. Success requires a verified receipt; ambiguous external outcomes remain explicit and operator-visible. |
| In-app fallback | The canonical in-app inbox is durable and independently available; external channel outage never silently discards an accepted intent. |

### 1.59 H3-09 accepted migration plan

H3-09 uses additive expand-first migration from accepted revision
`0029_h3_workflow_approval`. It adds only provider-neutral notification intent,
template/version, preference, digest, attempt, receipt, failure, and in-app inbox state
required by `H3_ARCHITECTURE.md`. Tenant keys include organization, workspace, and cell
identity; composite foreign keys preserve source, workflow, task, actor, destination,
job, attempt, and receipt boundaries; enabled and forced RLS exist before runtime
access. The migration rewrites no accepted H3-01 through H3-08 state and performs no
agent, UI, provider, connector, external-integration, business-data, H3-10+, or H4
backfill.

Empty-state downgrade MUST be proven. Once accepted intent, template, preference,
digest, attempt, receipt, failure, inbox, audit, or outbox evidence exists, destructive
schema downgrade MUST fail closed. Application rollback disables new external delivery
while retaining authorized read/export, cancellation, and in-app access; compatible
workers drain, and populated rollback requires a reviewed forward fix or export.

### 1.60 H3-09 implementation authorization

H3-09 is Accepted and merged through PR #42 at `e4ae56b`; its protected checks passed
and revision `0030_h3_notification_center` is the accepted production migration
baseline. Its acceptance evidence is `H3_09_ACCEPTANCE_EVIDENCE.md`. The next gate is
owned exclusively by the H3-10 governance sections below.

### 1.61 H3-10 accepted security-review scope

H3-10 security review MUST cover context-free or cross-workspace manifest, tool, plan,
delegation, model-policy, budget, orchestration, receipt, and verification access;
self-registration; manifest or tool-version substitution; direct SQL, repository,
provider SDK, shell, or arbitrary-code tools; prompt or plan injection; free-form
model output execution; delegation amplification; stale authorization; approval or
action-digest substitution; budget bypass; model-policy or emergency-disable bypass;
duplicate, reordered, cancelled, or replayed execution; unverifiable or ambiguous
outcomes; sensitive data egress; and H3-11, H4, UI, provider, connector, external
integration, or business-agent scope leakage. The review inherits H1 authorization,
execution context, audit/outbox/inbox/idempotency, H3-02 durable execution, H3-06 safe
context, H3-08 approvals, H3-09 notifications, and ADR-009/010/011/018/024/030.

### 1.62 H3-10 accepted classification and authorization impact

Every manifest/version, tool/version, delegation, plan/version, evidence reference,
model-policy decision, budget reservation, orchestration transition, action digest,
approval reference, command result, verification, receipt, audit event, and outbox
event records or inherits effective classification and policy version. Classification
is never less restrictive than contributing inputs. Canonical H1 authorization is
checked before registration, discovery, planning, context access, budget reservation,
approval use, command execution, replay, cancellation, verification, and receipt
access. Manifest ownership, tool registration, plan inclusion, or synthetic-agent
identity never grants permission; delegation only attenuates existing authority.

### 1.63 H3-10 accepted custody and lineage impact

The Agent Platform owns versioned manifests, registered tool metadata, typed inert
plans, delegations, budget evidence, orchestration state, verification, and receipts.
It does not own operational truth, provider state, credentials, documents, knowledge,
memory, tasks, workflows, notifications, or authorization. Tools reference versioned
application commands and queries, never SQL, repositories, SDK operations, shell
commands, arbitrary Python, provider payloads, or free-form prompts. Every plan and
receipt identifies its manifest/tool/model versions, evidence, actor/delegation,
classification, correlation/causation, action digest, policy, budget, command result,
verification, and explicit outcome.

### 1.64 H3-10 accepted retention and deletion impact

Manifests, tool versions, delegations, plans, evidence references, model-policy and
budget decisions, orchestration state, verifications, and receipts participate in
workspace retention, legal hold, export, closure, and deletion policy. Running work
retains its immutable version bindings. Revocation, closure, or emergency disable
prevents new execution and cancels eligible in-flight work while preserving minimum
accountability and disposition evidence. Cleanup cannot turn denied, expired,
cancelled, budget-exhausted, failed, or uncertain work into success.

### 1.65 H3-10 accepted recovery and orchestration impact

Recovery inventories manifest/tool/model versions, delegation scope, plan and evidence
digests, budgets, approval references, command/idempotency identities, orchestration
state, verifications, receipts, and checksums without reusable credentials, raw
prompts, governed source content, or provider payloads. Restore reconciles command,
approval, budget, and receipt identity before execution. Manifests, tools, models, and
orchestration can be disabled independently while in-flight work remains inspectable
and cancellable; no inert plan is promoted automatically during recovery.

### 1.66 H3-10 approved model, tool, approval, budget, and evaluation policy

This section is the single normative owner of H3-10 acceptance controls.

| Control | Approved requirement |
|---|---|
| Registration | Manifests and tools are owner-approved, typed, versioned, risk-classified, independently disableable, and immutable once referenced. Self-registration is prohibited. |
| Tool confinement | Every tool maps to a registered application command/query. Direct database, repository, provider SDK, shell, arbitrary-code, and free-form-prompt execution is prohibited. |
| Plans | Model output is untrusted; plans are typed, evidence-linked, versioned, budgeted, validated, and inert until explicitly accepted. |
| Delegation and authorization | Delegation only attenuates authority. Authorization, policy, resource version, action digest, and approval are revalidated at execution time. |
| Models and egress | Model selection follows approved classification and routing policy; context is minimized, cited, injection-resistant, and excludes secrets or disallowed data. |
| Budgets | Token, cost, tool-call, time, and concurrency ceilings fail closed and are reserved and receipted deterministically. |
| Execution and replay | Orchestration coordinates registered contracts through H3-02 jobs and H1 idempotency. Duplicate/reordered delivery and replay cannot duplicate accepted effects. |
| Verification and outcomes | Every action has immutable evidence and is verified or explicitly marked uncertain; model assertions never substitute for verification. |
| Evaluation and disable | Only synthetic conformance agents and versioned evaluation datasets are permitted. Emergency disable prevents new work and cancels eligible work within the accepted boundary. |

### 1.67 H3-10 accepted migration plan

H3-10 uses additive expand-first migration from accepted revision
`0030_h3_notification_center`. It adds only provider-neutral manifest/version,
tool/version, delegation, typed plan/version, model-policy, budget, orchestration,
verification, receipt, and synthetic-conformance state required by
`H3_ARCHITECTURE.md`. Tenant keys include organization, workspace, and cell identity;
composite foreign keys and enabled/forced RLS precede runtime access. The migration
rewrites no accepted H3-01 through H3-09 state and performs no business-agent, H3-11,
H4, UI, provider, connector, external-integration, or business-data backfill.

Empty-state downgrade MUST be proven. Once accepted manifest, tool, delegation, plan,
budget, orchestration, verification, receipt, audit, or outbox evidence exists,
destructive schema downgrade MUST fail closed. Application rollback disables new
planning and orchestration while retaining authorized inspection, cancellation, and
export; populated rollback requires a reviewed forward fix or export.

### 1.68 H3-10 implementation authorization

H3-09 is Accepted and merged through PR #42 at `e4ae56b`; its protected checks passed
and revision `0030_h3_notification_center` is the accepted production migration
baseline. The H3-10 impacts and controls above are approved. The H3-10 implementation
gate is open for one dedicated slice after this governance synchronization is merged
into `origin/master`. The acceptance-evidence target is
`H3_10_ACCEPTANCE_EVIDENCE.md`. H3-11, H4, provider-specific integrations, connectors,
business agents, external integrations, and UI functionality remain unauthorized.

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
