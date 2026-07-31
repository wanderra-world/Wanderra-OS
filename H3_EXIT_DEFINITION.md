# H3 Exit Definition — Atlas Platform Complete

Formal acceptance contract for the reusable Atlas platform before business agents.

**Owner:** Atlas Architecture Council  
**Status:** Proposed for review  
**Architecture:** [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md)  
**Implementation contract:** [H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md)

## 1. Meaning of “Atlas Platform Complete”

Atlas Platform Complete means Atlas has a secure, provider-neutral, workspace-isolated,
recoverable, observable, and reusable platform on which separately authorized business
agents can be built without adding another general-purpose foundation layer.

It does **not** mean:

- every business capability or provider exists;
- every business agent exists;
- the platform will never evolve;
- maintenance, measured scaling, isolated improvements, or new ADRs stop;
- broad autonomy is authorized;
- H3 completion automatically authorizes a business agent.

After Formal H3 Exit, new reusable foundation work should be exceptional and justified
by a concrete business-agent need, measured operational evidence, or security change.

## 2. Mandatory completion gates

All gates below MUST pass. A narrative assertion without reproducible evidence does
not pass a gate.

### Gate A — Accepted baseline and slice closure

- Formal H0, H1, and H2 exits remain accepted.
- H3-01 through H3-10 are explicitly accepted and merged.
- H3-11 contains only integration evidence, approved remediation, and Formal H3 Exit.
- No business agent, business workflow, Trading, Wanderra, or H4 implementation exists.

### Gate B — Workspace and security integrity

- Every tenant-owned H3 row has enforced organization/workspace/cell integrity.
- Every applicable table has enabled and forced RLS under non-owner, non-bypass roles.
- Cross-workspace read, write, join, graph, search, memory, workflow, job, notification,
  export, restore, uniqueness, and model-egress attacks fail.
- Revoked identity, session, membership, delegation, connection, credential, tool,
  workflow, model, or approval takes effect within its defined boundary and SLO.
- No unresolved critical or high security finding lacks explicit, time-bounded risk
  acceptance by the accountable authority.

### Gate C — Canonical resource and data-plane integrity

- Universal resource identity is constrained to approved typed operational aggregates.
- Projection/resource creation is transactional and orphan-free.
- Relationships, tags, attachments, notes, ownership, and grants are workspace-safe.
- Operational Data, Documents, Knowledge, Memory, Timeline, and Audit remain distinct
  in models, authority, retention, APIs, and tests.
- At least one synthetic provider-neutral vertical slice links a typed resource,
  provider email/calendar/file, task, document, knowledge claim, memory, timeline, and
  search result without provider leakage.

### Gate D — Durable execution and scheduling

- Jobs survive worker crash, lease expiry, retries, duplicate delivery, reordering,
  cancellation, timeout, dead letter, and authorized replay.
- Scheduler behavior is deterministic across clock skew, downtime, timezone, and DST.
- Backpressure, bounded concurrency, tenant fairness, quota, and emergency pause are
  proven under load.
- External effects are idempotent or use version preconditions and verification; Atlas
  does not claim system-wide exactly-once delivery.

### Gate E — Documents and derivative governance

- Document versions are immutable, content-addressed, classified, and held in approved
  object custody.
- Unverified/quarantined content cannot reach extraction or models.
- Every chunk, claim, memory, embedding, index record, note, and timeline derivative
  identifies its source and producing version.
- Retention and legal hold override deletion correctly.
- Source deletion propagates across object storage, PostgreSQL, indexes, embeddings,
  caches, exports, and backups, or yields an explicit auditable exception.

### Gate F — Knowledge, memory, search, and AI safety

- Knowledge claims cite accessible evidence and preserve contradiction/supersession.
- Memory has provenance, classification, confidence, feedback, expiry, user control,
  export, and deletion.
- Neither knowledge nor memory silently mutates operational truth.
- Search permission filters execute before candidate retrieval and response assembly.
- Revoked permissions and deletions meet approved index freshness SLOs.
- Hybrid search meets accepted relevance, latency, isolation, and freshness thresholds.
- Context assembly preserves citations, minimizes data, treats content as untrusted,
  enforces classification/model policy, and resists prompt injection and data egress.

### Gate G — Tasks, workflows, and notifications

- Canonical tasks support human and synthetic-agent provenance without granting
  implicit permission.
- Workflow definitions are versioned, immutable for running instances, replay-safe,
  pauseable, cancellable, and approval-aware.
- Workflows invoke only registered commands/queries and cannot execute arbitrary code,
  SQL, prompts, repository methods, or provider SDK operations.
- Notification intents are authorized, preference-aware, classified, minimized,
  deduplicated, rate-limited, and auditable.
- Failure, compensation, uncertain outcome, and operator-intervention states are
  explicit and recoverable.

### Gate H — Agent platform readiness

- Agent and tool manifests are versioned, owner-approved, risk-classified, budgeted,
  and independently disableable.
- Synthetic agents prove that delegation only attenuates authority.
- Plans are typed, evidence-linked, versioned, and inert until validated.
- Free-form model output cannot directly execute.
- Every tool maps to the same application command/query boundary used by humans.
- Authorization, approval digest, resource version, budgets, and policy are revalidated
  at execution time.
- Every action has a receipt and is verified or explicitly marked uncertain.
- Emergency disable cancels or prevents new work within the approved SLO.

### Gate I — Provider neutrality and compatibility

- Business/application/H3 modules contain no Google SDK or payload dependency.
- Gmail, Calendar, and Drive continue to pass canonical H2 conformance and Phase 1
  compatibility tests.
- At least one deterministic non-Google provider passes applicable shared contracts.
- H2 legacy/shadow/canonical rollback remains operational until separately retired.
- No valid credential, external identity, provider reference, or Phase 1 identifier is
  lost during H3 migration.

### Gate J — Observability and operations

- Logs, metrics, traces, audit references, job/workflow spans, model/tool usage, cost,
  and outcome signals are correlated and redacted.
- Operators can inspect, pause, cancel, quarantine, replay, reconcile, disable, and
  resume each execution boundary without direct database mutation.
- Alerting, dashboards, runbooks, and escalation ownership exist for approved SLOs.
- Backup, restore, export, closure, retention, erasure, and disaster recovery include
  every H3-owned record and object.
- Measured RPO/RTO, load, soak, failure-budget, and cost ceilings pass.

### Gate K — Engineering and architecture fitness

- Complete H0/H1/H2/H3 regression, PostgreSQL/RLS, migration, rollback/forward-fix,
  architecture, security, type, lint, Docker, worker, and production smoke suites pass.
- Fitness tests reject context-free repositories, provider leakage, direct cross-context
  writes, EAV aggregates, vector authorization, unregistered tools, direct agent data
  access, missing lineage, and missing forced RLS.
- Every public contract and persisted schema is versioned where compatibility requires.
- Every compatibility exception has an owner, removal criterion, and review date.
- Protected CI and branch policies are green and cannot be bypassed.

## 3. Required Formal H3 Exit evidence

H3-11 MUST produce:

- `H3_EVIDENCE_MATRIX.md`, tracing every slice and gate to tests and evidence;
- `H3_SECURITY_REVIEW.md`, including AI, tool, workflow, retrieval, tenant, and
  derivative-lineage threats with residual risk;
- `H3_RECOVERY_REPORT.md`, covering backup/restore, RPO/RTO, closure, export, deletion,
  worker/workflow recovery, and operator drills;
- `H3_EVALUATION_REPORT.md`, covering search quality, prompt injection, model egress,
  planning, tool selection, outcomes, latency, cost, and reliability;
- `H3_EXIT_REPORT.md`, recording the final decision and accepted platform baseline;
- protected GitHub evidence for the complete merge-blocking gate.

Evidence MUST contain no reusable credential, secret, governed source content, raw
prompt, or sensitive provider payload.

## 4. Formal decision states

The Formal H3 Exit decision is exactly one of:

- **Accepted:** every gate passes, H3-11 required checks pass, the exit report is
  reviewed, and the H3-11 pull request is merged;
- **Conditionally accepted:** prohibited for critical/high security, tenancy,
  authorization, deletion, recovery, or agent-boundary failures; allowed only for a
  non-safety operational finding with named owner, deadline, monitoring, and explicit
  Architecture Council approval;
- **Rejected:** any mandatory gate lacks reproducible evidence or a prohibited finding
  remains.

The repository MUST NOT claim “Atlas Platform Complete” before the Accepted state is
effective on the protected default branch.

## 5. Post-exit boundary

Formal H3 Exit permits proposals for business agents and business modules. Each such
agent still requires:

- a business owner and bounded purpose;
- workspace and data-classification scope;
- registered tools and attenuated permissions;
- risk, approval, budget, outcome, and emergency-disable policy;
- evaluation data and measurable acceptance thresholds;
- dedicated architecture and implementation authorization.

Formal H3 Exit does not authorize H4, Trading, Wanderra, or any other business-agent
implementation automatically.
