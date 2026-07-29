# Atlas Architecture Hardening Plan

**Owner:** Atlas Architecture Council  
**Status:** H0 validation authorized; executable gate evidence pending  
**Source:** `ARCHITECTURE_REVIEW.md`  
**Planning horizon:** Phase 2 foundation through future platform evolution

## How to read this plan

Priorities mean:

- **P0 — Must fix before implementation:** architecture or specification work that must
  be complete before Phase 2 production schema and feature development begins.
- **P1 — Must fix during Phase 2:** required before Phase 2 is considered complete;
  sequence it before dependent capabilities.
- **P2 — Can wait until Phase 3:** important, but should not distort the Phase 2 core.
- **P3 — Future consideration:** deliberately deferred until demand or scale is proven.

The issue descriptions below own prioritization, problem, risk, dependencies, and
effort only. Approved P0 implementation contracts are owned by
`H0_FOUNDATION_SPEC.md`; engineering execution gates are owned by
`IMPLEMENTATION_GUIDE.md`.

Effort estimates are engineering effort, not elapsed calendar time. They assume
experienced engineers, include design and tests, and exclude procurement/compliance
lead times. Ranges are intentionally broad until technology selections and threat
models are approved.

# P0 — Must fix before implementation

## P0.1 Tenant key and database isolation strategy

- **Problem:** Shared-schema tenancy relies too heavily on application predicates.
  Cross-workspace foreign keys and pooled RLS context are not specified.
- **Risk:** A missing filter, incorrect job context, privileged connection, or pooled
  session leak can expose or mutate another workspace.
- **Recommended solution:** Define workspace-inclusive candidate keys and composite
  foreign keys for all tenant aggregates. Specify RLS roles, transaction-local workspace
  context, pool reset behavior, migration/support roles, and automated cross-tenant
  attack tests. Add a workspace placement/cell ID without deploying multiple cells yet.
- **Estimated effort:** 3–5 engineer-weeks for specification, prototype, migration
  rehearsal, and fitness tests.
- **Dependencies:** Workspace ownership hierarchy; database role model; request context.
- **Changes architecture documents:** **Yes.** Replace ADR-014; amend architecture
  invariants, tenancy, migration, and domain key conventions.

## P0.2 Organization and workspace ownership hierarchy

- **Problem:** Organization is optional and its authority over workspaces is undefined.
- **Risk:** Ambiguous billing, legal ownership, administrator access, SSO, retention,
  workspace transfer, and Personal workspace behavior.
- **Recommended solution:** Make every workspace belong to exactly one organization.
  Define organization types, owner lifecycle, organization administrators, workspace
  transfer prohibition or protocol, and explicit content-access rules. Model Personal
  as a private organization/workspace configuration, not a tenancy exception.
- **Estimated effort:** 1–2 engineer-weeks.
- **Dependencies:** Identity lifecycle; authorization policy.
- **Changes architecture documents:** **Yes.** Amend ADR-001, domain model, and roadmap.

## P0.3 Identity and session lifecycle specification

- **Problem:** OIDC and MFA are mentioned without identity linking, recovery, session
  revocation, invitation security, or compromised-account behavior.
- **Risk:** Account takeover, orphaned ownership, unverifiable audit history, and
  inconsistent identities across providers.
- **Recommended solution:** Specify canonical user identity, verified email handling,
  external identity links, invitations, recovery, session/device records, revocation,
  MFA requirements, account merge prohibition/protocol, and service/support identities.
  Choose the initial identity provider and token/session architecture.
- **Estimated effort:** 3–5 engineer-weeks including a security review and prototype.
- **Dependencies:** Organization/workspace hierarchy; threat model.
- **Changes architecture documents:** **Yes.** Expand Identity and Access architecture
  and add an ADR.

## P0.4 Implementable authorization model

- **Problem:** “RBAC plus contextual policy” does not define evaluation, precedence,
  grants, groups, caching, or revocation.
- **Risk:** Privilege escalation, role explosion, inconsistent enforcement, and
  approvals by unauthorized actors.
- **Recommended solution:** Define a governed permission vocabulary, fixed initial
  roles, explicit-deny precedence, team/group semantics, exceptional resource grants,
  ownership rules, support/break-glass access, policy decision API, revocation latency,
  and decision explanations. Require authorization at application-command boundaries.
- **Estimated effort:** 4–7 engineer-weeks for design, policy prototype, and test matrix.
- **Dependencies:** Identity/session lifecycle; tenant model; request context.
- **Changes architecture documents:** **Yes.** Replace ADR-009 and revise domain/API
  boundaries.

## P0.5 Formal threat model

- **Problem:** Security controls are listed without trust boundaries, assets, attackers,
  abuse cases, or prioritized mitigations.
- **Risk:** Cross-tenant leaks, provider credential theft, webhook spoofing, agent tool
  abuse, prompt injection, and unrecognized high-impact attack paths.
- **Recommended solution:** Produce data-flow diagrams and STRIDE-style analysis for
  authentication, workspace access, providers, webhooks, jobs, documents, search,
  models, agents, approvals, and support operations. Track mitigations and residual risk.
- **Estimated effort:** 2–4 engineer-weeks plus external review.
- **Dependencies:** Draft identity, tenancy, provider, and AI boundaries.
- **Changes architecture documents:** **Yes.** Add security ADRs and reference the
  threat model from architecture and roadmap.

## P0.6 Versioned envelope encryption

- **Problem:** Phase 1 uses one Fernet key; managed encryption is deferred.
- **Risk:** One compromised key exposes every provider credential. There is no safe
  rotation, rewrap, revocation, or per-record blast-radius control.
- **Recommended solution:** Design and prototype per-record data keys wrapped by managed
  KMS, ciphertext key versions, authenticated encryption context containing workspace
  and connection IDs, rotation/rewrap jobs, access audit, and emergency revocation.
- **Estimated effort:** 3–5 engineer-weeks plus cloud/KMS setup.
- **Dependencies:** Connection identity; cloud environment; threat model.
- **Changes architecture documents:** **Yes.** Change ADR-013 from target to prerequisite.

## P0.7 Object storage and document custody

- **Problem:** The design defines document versions but no durable object store.
- **Risk:** Provider outages or deletion can destroy evidence; PostgreSQL may be abused
  for blobs; extraction cannot be reproduced.
- **Recommended solution:** Select object storage and define content-addressed immutable
  versions, tenant prefixes, encryption, signed access, quarantine, malware scanning,
  hashes, regional placement, lifecycle, legal hold, and backup behavior.
- **Estimated effort:** 3–5 engineer-weeks including a proof of concept.
- **Dependencies:** Encryption, classification, retention, workspace placement.
- **Changes architecture documents:** **Yes.** Add object storage to system architecture
  and amend ADR-015.

## P0.8 Provider mirror, authority, and conflict model

- **Problem:** Capability ports omit provider resource mirrors, field authority, merge
  rules, and concurrent external changes.
- **Risk:** Atlas canonical records become ambiguous or silently overwrite provider
  truth.
- **Recommended solution:** Specify provider mirror records, canonicalization states,
  per-resource/field authority, etags/versions, conflict detection, tombstones, merge
  policy, user resolution, and outbound preconditions. Separate capability contracts
  from synchronization contracts.
- **Estimated effort:** 4–7 engineer-weeks with Google examples and a mock second
  provider.
- **Dependencies:** Universal/external identity scope; connection model.
- **Changes architecture documents:** **Yes.** Split/amend ADR-004 and expand the domain
  model.

## P0.9 Deletion, retention, and derivation lineage

- **Problem:** No complete deletion graph covers sources, operational records,
  extraction, claims, memory, embeddings, indexes, caches, backups, audit, and providers.
- **Risk:** Atlas cannot honor deletion, retention, legal hold, or workspace closure.
- **Recommended solution:** Define lineage between every source and derivative, policy
  precedence, tombstone/erase behavior, cryptographic erasure where applicable, legal
  hold, backup expiry, provider deletion policy, and deletion verification receipts.
- **Estimated effort:** 4–6 engineer-weeks for policy and reference implementation design.
- **Dependencies:** Data planes; object storage; provider conflict model; audit policy.
- **Changes architecture documents:** **Yes.** Expand ADR-005 and add a retention ADR.

## P0.10 AI security and data-egress model

- **Problem:** Permission-aware search does not address prompt injection, context
  over-collection, model retention, embeddings, or tool-instruction attacks.
- **Risk:** Sensitive or cross-workspace data exfiltration and unauthorized agent actions.
- **Recommended solution:** Define trust labels for content, instruction/data
  separation, context minimization, model-provider data policy, workspace/model routing,
  output/egress classification, tool isolation, prompt-injection handling, red-team
  tests, and model logging rules.
- **Estimated effort:** 3–6 engineer-weeks initially; ongoing program afterward.
- **Dependencies:** Threat model; classification; authorization; provider/model choices.
- **Changes architecture documents:** **Yes.** Expand security and agent architecture;
  add AI security ADR.

## P0.11 Universal entity/projection integrity

- **Problem:** A polymorphic entity registry can drift from typed projections.
- **Risk:** Orphaned entities, incompatible projections, incorrect entity types, broken
  relationships, and global migration difficulty.
- **Recommended solution:** Limit which aggregates become entities. Define an entity
  type registry, transactional factory, exactly-one projection rules where applicable,
  lifecycle/delete protocol, type/version migrations, and database integrity checks.
- **Estimated effort:** 2–4 engineer-weeks with schema prototype.
- **Dependencies:** Minimum canonical core; tenant key strategy.
- **Changes architecture documents:** **Yes.** Amend ADR-003 and domain model.

## P0.12 Minimum canonical core and scope reduction

- **Problem:** The proposed foundation attempts to anticipate finance, shipments,
  properties, vehicles, knowledge graphs, recommendations, and agents simultaneously.
- **Risk:** Speculative abstractions delay value and harden incorrect assumptions.
- **Recommended solution:** Freeze Phase 2 core scope to tenancy, IAM, connections,
  external references, entity identity/relationships, contacts, companies, projects,
  tasks, documents, activity, audit, and search. Treat all other areas as modules.
- **Estimated effort:** 1–2 engineer-weeks of model and roadmap revision.
- **Dependencies:** Entity integrity; business-priority agreement.
- **Changes architecture documents:** **Yes.** Narrow domain model and roadmap; annotate
  deferred sections.

## P0.13 Event, idempotency, and concurrency specification

- **Problem:** The outbox decision omits aggregate ordering, schema compatibility,
  inboxes, poison events, replay, idempotency scope, and optimistic concurrency.
- **Risk:** Duplicated external actions, corrupt projections, lost updates, and unsafe
  replay.
- **Recommended solution:** Define event envelope/versioning, aggregate sequence,
  transactional outbox/inbox, delivery semantics, replay authorization, dead letters,
  idempotency-key ownership/retention, aggregate versions, and command preconditions.
- **Estimated effort:** 3–5 engineer-weeks with a reference vertical slice.
- **Dependencies:** Aggregate boundaries; database strategy; audit.
- **Changes architecture documents:** **Yes.** Amend ADR-008 and API/event sections.

## P0.14 Architecture fitness tests

- **Problem:** Module boundaries and tenancy invariants exist only in prose.
- **Risk:** The first implementation will erode them unnoticed.
- **Recommended solution:** Specify automated checks for forbidden imports, tenant
  columns/composite FKs, command authorization, audit/outbox emission, provider contract
  conformance, event compatibility, cross-tenant access, and deletion propagation.
- **Estimated effort:** 2–4 engineer-weeks for the initial harness.
- **Dependencies:** Decisions P0.1–P0.13.
- **Changes architecture documents:** **Yes.** Add fitness tests as hard roadmap exit
  criteria and a testing ADR.

# P1 — Must fix during Phase 2

## P1.1 Durable background job platform

- **Problem:** Required semantics are listed but no technology or worker contract is
  selected.
- **Risk:** Lost, duplicated, stuck, or unobservable sync/extraction/indexing work.
- **Recommended solution:** Select a durable job mechanism; define leases, heartbeats,
  retry classes, cancellation, idempotency, dead letters, priorities, schedules, and
  per-workspace fairness.
- **Estimated effort:** 4–7 engineer-weeks.
- **Dependencies:** Event/idempotency specification; observability.
- **Changes architecture documents:** **Yes.** Finalize ADR-019.

## P1.2 Tamper-evident audit

- **Problem:** Same-database audit is complete but mutable by privileged actors.
- **Risk:** Weak forensic evidence and undetectable history alteration.
- **Recommended solution:** Restrict append permissions, separate audit writer/reader
  roles, hash-chain or sign batches, export to immutable storage, verify periodically,
  and define redaction.
- **Estimated effort:** 3–5 engineer-weeks.
- **Dependencies:** Object storage; KMS; audit schema.
- **Changes architecture documents:** **Yes.** Amend audit architecture and ADR-017.

## P1.3 Execution-time approval safety

- **Problem:** Action digests do not handle changed resources or policies after approval.
- **Risk:** An approved action executes against unsafe current state.
- **Recommended solution:** Add approval expiry, runtime policy re-evaluation, resource
  version/etag preconditions, recipient/account re-verification, spend limits, stale
  approval invalidation, and immutable execution receipts.
- **Estimated effort:** 3–5 engineer-weeks before R2/R3 automation.
- **Dependencies:** Authorization; provider versions; command concurrency.
- **Changes architecture documents:** **Yes.** Amend ADR-010 and ADR-011.

## P1.4 Backup, restore, and disaster recovery

- **Problem:** No RPO, RTO, key recovery, restore testing, or provider reconciliation
  procedure.
- **Risk:** Extended outage or unrecoverable business data.
- **Recommended solution:** Set service tiers and RPO/RTO; automate encrypted backups;
  restore into isolated environments; recover KMS access; reconcile providers after
  restore; test workspace export/restore.
- **Estimated effort:** 3–6 engineer-weeks plus recurring exercises.
- **Dependencies:** Object storage; database; KMS; provider mirror.
- **Changes architecture documents:** **Yes.** Add reliability ADR and roadmap gate.

## P1.5 Data classification and propagation

- **Problem:** Sensitivity is named but classification rules are not defined.
- **Risk:** Search, models, exports, logs, and agents mishandle sensitive content.
- **Recommended solution:** Define classification levels, defaults, inheritance,
  downgrade authority, model/egress restrictions, log redaction, and propagation through
  derivations and relationships.
- **Estimated effort:** 2–4 engineer-weeks.
- **Dependencies:** Threat model; retention; search; memory.
- **Changes architecture documents:** **Yes.** Expand security/domain model.

## P1.6 Provider webhook and synchronization security

- **Problem:** Signature verification is listed but replay, tenant routing, raw payload
  custody, and subscription rotation are not specified.
- **Risk:** Forged events, cross-workspace routing, replayed mutations, and webhook loss.
- **Recommended solution:** Provider-specific ingress isolation, signature/time-window
  verification, deduplication, connection routing, raw-event quarantine, subscription
  renewal, reconciliation, and ingress rate limits.
- **Estimated effort:** 3–5 engineer-weeks per initial provider family.
- **Dependencies:** Connections; jobs; event semantics; object storage.
- **Changes architecture documents:** **Yes.** Expand provider/security sections.

## P1.7 Search authorization and embedding governance

- **Problem:** Visibility filtering is high level; embeddings and index deletion are
  under-designed.
- **Risk:** Search leakage, stale permissions, sensitive semantic inference, and
  undeleted derived data.
- **Recommended solution:** Define search ACL projection, prefilter guarantees,
  permission-version invalidation, sensitive embedding policy, source/content hashes,
  model migration, deletion lineage, and retrieval isolation tests.
- **Estimated effort:** 5–8 engineer-weeks.
- **Dependencies:** Authorization; classification; lineage; pgvector.
- **Changes architecture documents:** **Yes.** Amend ADR-012 and search design.

## P1.8 Activity, timeline, event, and audit storage contract

- **Problem:** Four overlapping record types can duplicate data inconsistently.
- **Risk:** Storage explosion, contradictory history, unreliable rebuilds.
- **Recommended solution:** Define one domain event envelope, explicit projections,
  minimal audit payload, timeline rendering contract, retention/partitioning, and which
  records are rebuildable.
- **Estimated effort:** 2–4 engineer-weeks.
- **Dependencies:** Event specification; audit; retention.
- **Changes architecture documents:** **Yes.** Clarify ADR-005 and ADR-017.

## P1.9 Provider capability negotiation

- **Problem:** Provider-neutral ports risk lowest-common-denominator interfaces.
- **Risk:** Leaky provider checks or inability to expose valuable features.
- **Recommended solution:** Versioned base contracts plus explicit optional capabilities,
  discovery, canonical error taxonomy, extensions envelope, and conformance suites.
- **Estimated effort:** 3–5 engineer-weeks for email/calendar/storage contracts.
- **Dependencies:** Provider mirror/authority model.
- **Changes architecture documents:** **Yes.** Amend ADR-004.

## P1.10 Entity resolution and identity merge

- **Problem:** Contacts and companies from multiple providers need canonical matching,
  but merge/split semantics are absent.
- **Risk:** Duplicate people, incorrectly merged identities, lost provenance, and
  communication errors.
- **Recommended solution:** Conservative candidate matching, explicit merge review,
  reversible merge lineage, immutable external references, split tooling, confidence,
  and no automatic high-risk merges.
- **Estimated effort:** 4–7 engineer-weeks.
- **Dependencies:** Entity registry; provider mirrors; audit.
- **Changes architecture documents:** **Yes.** Expand contact/domain model.

## P1.11 Observability and provider operations

- **Problem:** No concrete SLOs, sync freshness, quota budgets, or operational dashboards.
- **Risk:** Failures remain invisible until users report missing or stale data.
- **Recommended solution:** Define API/job/sync SLOs, structured logs, traces, metrics,
  correlation, connection health, provider quota/rate-limit dashboards, and alerting.
- **Estimated effort:** 3–6 engineer-weeks plus ongoing instrumentation.
- **Dependencies:** Jobs; provider contracts; deployment platform.
- **Changes architecture documents:** **Yes.** Add measurable SLOs.

## P1.12 Migration rehearsal and rollback/forward-fix plan

- **Problem:** Expand-and-contract is stated without concrete data validation, rollback,
  credential migration, or dual-write failure policy.
- **Risk:** Phase 1 outage, lost credentials, duplicated resources, or inconsistent
  ownership.
- **Recommended solution:** Rehearse on a production-like copy; inventory and checksum
  rows; shadow/dual-read; define cutover flags, forward-fix boundaries, credential
  re-encryption, reauthorization fallback, and compatibility-code removal.
- **Estimated effort:** 3–6 engineer-weeks.
- **Dependencies:** P0 schema/security decisions; migration tooling.
- **Changes architecture documents:** **Yes.** Expand Phase 1 migration plan.

## P1.13 API mutation semantics

- **Problem:** Idempotency, pagination, version conflicts, bulk operations, and standard
  errors are only mentioned.
- **Risk:** Duplicate external effects, lost updates, unstable clients, and poor retry
  behavior.
- **Recommended solution:** Define HTTP command conventions, idempotency headers,
  optimistic versions/ETags, cursor format, problem details, long-running operation
  resources, rate limits, and contract tests.
- **Estimated effort:** 2–4 engineer-weeks.
- **Dependencies:** Event/idempotency design; domain versions.
- **Changes architecture documents:** **Yes.** Add API standards ADR.

## P1.14 Workspace export, closure, and placement portability

- **Problem:** Workspaces are isolation units but lack export, closure, transfer, and
  future cell migration contracts.
- **Risk:** Customer lock-in, incomplete deletion, and inability to isolate large tenants.
- **Recommended solution:** Define versioned export manifest, content bundles, key
  handling, closure state machine, retention/legal hold, placement routing, and migration
  verification.
- **Estimated effort:** 4–7 engineer-weeks.
- **Dependencies:** Lineage; object storage; tenancy; encryption.
- **Changes architecture documents:** **Yes.** Amend ADR-014 replacement and roadmap.

## P1.15 Capacity, performance, and cost model

- **Problem:** The architecture has no workload assumptions for entities, messages,
  files, events, embeddings, sync frequency, API latency, or model spend.
- **Risk:** PostgreSQL hot tables, timeline/audit growth, provider quota exhaustion,
  runaway AI cost, and arbitrary infrastructure extraction.
- **Recommended solution:** Define three-year low/expected/high workload models,
  per-workspace fairness, latency/throughput targets, storage growth, partition/index
  plans, connection-pool budgets, model/token budgets, and measurable extraction
  thresholds for queues, search, cells, and services.
- **Estimated effort:** 2–4 engineer-weeks initially; quarterly revision.
- **Dependencies:** Minimum core, SLOs, provider/job designs.
- **Changes architecture documents:** **Yes.** Add quantified scalability thresholds to
  ADR-006 and operations architecture.

## P1.16 Privacy governance and user rights

- **Problem:** Controller/processor roles, consent, subject access, correction, export,
  objection, and model-evaluation reuse are not defined.
- **Risk:** Legal non-compliance and inability to explain or remove personal data.
- **Recommended solution:** Map data categories and legal purposes per workspace;
  implement subject-access/export workflows, correction/erasure intake, consent where
  required, evaluation-dataset governance, Personal workspace policy, and documented
  controller/processor responsibilities.
- **Estimated effort:** 3–6 engineer-weeks plus legal counsel.
- **Dependencies:** Classification, lineage, retention, workspace export.
- **Changes architecture documents:** **Yes.** Add privacy architecture and roadmap
  gates.

# P2 — Can wait until Phase 3

## P2.1 Custom workspace roles

- **Problem:** Custom roles create policy and support complexity before fixed roles are
  validated.
- **Risk:** Role explosion and unexplainable access.
- **Recommended solution:** Ship fixed versioned roles first; add custom roles only from
  observed gaps with privilege-escalation safeguards.
- **Estimated effort:** 3–5 engineer-weeks later.
- **Dependencies:** Mature permission vocabulary and policy UI.
- **Changes architecture documents:** **Yes.** Mark as deferred.

## P2.2 Generalized knowledge claims

- **Problem:** Temporal subject-predicate-object claims and contradiction resolution are
  a speculative product.
- **Risk:** Major ontology/moderation investment before basic retrieval works.
- **Recommended solution:** Start with entities, relationships, sources, and extracted
  attributes; introduce claims for demonstrated use cases.
- **Estimated effort:** 8–16 engineer-weeks when justified.
- **Dependencies:** Documents, provenance, review workflows, search evaluation.
- **Changes architecture documents:** **Yes.** Reclassify as Phase 3.

## P2.3 Graph-enhanced search ranking

- **Problem:** Graph proximity is proposed without evidence it improves results.
- **Risk:** Expensive queries and opaque ranking.
- **Recommended solution:** Establish lexical/vector baseline and evaluation corpus;
  add graph features only when measured.
- **Estimated effort:** 4–8 engineer-weeks.
- **Dependencies:** Stable graph and search metrics.
- **Changes architecture documents:** **Yes.** Defer in ADR-012.

## P2.4 Finance operational module

- **Problem:** Atlas risks becoming an accounting system without the necessary domain
  and regulatory depth.
- **Risk:** Incorrect books, taxes, approvals, and legal exposure.
- **Recommended solution:** Initially integrate accounting providers and support invoice
  workflow. Design a ledger only with specialist expertise and a separate ADR set.
- **Estimated effort:** 12–30+ engineer-weeks depending on scope.
- **Dependencies:** Provider framework; approvals; audit; domain expertise.
- **Changes architecture documents:** **Yes.** Narrow ADR-016.

## P2.5 Vertical asset and shipment models

- **Problem:** Property, vehicle, equipment, and shipment schemas are speculative.
- **Risk:** Incorrect generalization across businesses.
- **Recommended solution:** Build as bounded modules from real workflows; promote only
  proven shared concepts.
- **Estimated effort:** 6–16 engineer-weeks per module.
- **Dependencies:** Core entities/projects/tasks/documents.
- **Changes architecture documents:** **Yes.** Mark typed models as illustrative.

## P2.6 Recommendation lifecycle and outcome measurement

- **Problem:** Full recommendation aggregates precede reliable context and evaluation.
- **Risk:** Storing noisy suggestions and creating false trust.
- **Recommended solution:** Add after search, evidence, feedback, and workspace policy
  are mature; begin read-only.
- **Estimated effort:** 5–10 engineer-weeks.
- **Dependencies:** Search, memory governance, AI security, metrics.
- **Changes architecture documents:** No fundamental change; roadmap deferral.

## P2.7 Advanced approval policies

- **Problem:** Quorum, sequential, separation-of-duties, and amount thresholds may be
  unnecessary initially.
- **Risk:** Workflow complexity and stuck approvals.
- **Recommended solution:** Start with single explicit approver and fixed risk policy;
  add advanced policies with finance/enterprise demand.
- **Estimated effort:** 5–10 engineer-weeks.
- **Dependencies:** Basic approvals, IAM, workflow engine.
- **Changes architecture documents:** Yes, clarify staged capability.

## P2.8 SSO and SCIM

- **Problem:** Initial workspaces may not require enterprise provisioning immediately.
- **Risk:** Manual lifecycle work and delayed revocation for larger teams.
- **Recommended solution:** Preserve external identity/group contracts in P0; implement
  SAML/OIDC enterprise SSO and SCIM when multi-user customers require them.
- **Estimated effort:** 6–12 engineer-weeks.
- **Dependencies:** Mature identity and organization policy.
- **Changes architecture documents:** No; add roadmap timing.

## P2.9 Regional data placement

- **Problem:** No immediate multi-region demand is proven.
- **Risk:** Later residency requirements can force migration.
- **Recommended solution:** Keep cell/placement abstraction and region metadata in P0;
  deploy multiple regions only with legal/customer need.
- **Estimated effort:** 10–25+ engineer-weeks later.
- **Dependencies:** Cell-ready tenancy, object storage, KMS, DR.
- **Changes architecture documents:** No after P0 cell amendment.

## P2.10 Analytics warehouse

- **Problem:** PostgreSQL should not become the long-term analytics platform.
- **Risk:** Operational query contention and retention pressure.
- **Recommended solution:** Define governed event export; add a warehouse only after
  analytical workloads and consent rules are known.
- **Estimated effort:** 6–12 engineer-weeks.
- **Dependencies:** Event schemas, classification, audit, privacy.
- **Changes architecture documents:** Add future data-platform boundary.

## P2.11 General-purpose service principals

- **Problem:** A broad non-human identity system is proposed before use cases are known.
- **Risk:** Permanent credentials, privilege sprawl, and difficult attribution.
- **Recommended solution:** In Phase 2 support only tightly scoped internal worker and
  verified webhook actors. Add customer-managed service principals later with expiry,
  rotation, workload identity, and explicit workspace grants.
- **Estimated effort:** 4–8 engineer-weeks later.
- **Dependencies:** Mature IAM, audit, API credential lifecycle.
- **Changes architecture documents:** **Yes.** Narrow the initial actor model.

## P2.12 Relationship-type administration

- **Problem:** A dynamic relationship schema/cardinality registry can become another
  meta-modeling platform.
- **Risk:** Invalid graphs, difficult migrations, and workspace-specific ontology drift.
- **Recommended solution:** Begin with code/version-controlled relationship types for
  the minimum core. Add controlled extension only after real module needs appear.
- **Estimated effort:** 3–6 engineer-weeks later.
- **Dependencies:** Stable entity modules and graph usage.
- **Changes architecture documents:** **Yes.** Narrow the initial relationship registry.

# P3 — Future consideration

## P3.1 Cross-workspace sharing and reasoning

- **Problem:** Explicit sharing is architecturally possible but multiplies isolation and
  revocation complexity.
- **Risk:** Accidental business/personal data leakage.
- **Recommended solution:** Keep prohibited by default. Design a separate sharing product
  with copied/reference semantics and revocation propagation if demand appears.
- **Estimated effort:** 10–20+ engineer-weeks.
- **Dependencies:** Mature IAM, lineage, search ACLs, audit.
- **Changes architecture documents:** No; retain prohibition.

## P3.2 Partner integration SDK

- **Problem:** Public contracts would freeze immature provider abstractions.
- **Risk:** Long-lived compatibility burden and unsafe third-party adapters.
- **Recommended solution:** Stabilize several internal providers first; later add
  sandboxing, manifest permissions, certification, and version policy.
- **Estimated effort:** 12–24+ engineer-weeks.
- **Dependencies:** Mature provider contracts and developer platform.
- **Changes architecture documents:** Roadmap timing only.

## P3.3 Multi-agent planning

- **Problem:** Multi-agent systems add nondeterminism before basic commands and
  evaluations are mature.
- **Risk:** Unbounded cost, unclear responsibility, and compounded errors.
- **Recommended solution:** Begin with one governed orchestrator and deterministic tools.
  Add specialized agents only when evaluation proves benefit.
- **Estimated effort:** 10–20+ engineer-weeks.
- **Dependencies:** Agent security, workflows, approvals, evaluation platform.
- **Changes architecture documents:** Narrow initial agent architecture.

## P3.4 Compensation framework

- **Problem:** Generic rollback across external providers is often impossible.
- **Risk:** False promise of reversibility.
- **Recommended solution:** Model per-command compensating actions and irreversibility;
  build a framework only after repeated patterns emerge.
- **Estimated effort:** 5–12 engineer-weeks.
- **Dependencies:** Mature command catalog and provider semantics.
- **Changes architecture documents:** Clarify that compensation is capability-specific.

## P3.5 External search engine

- **Problem:** PostgreSQL limits are not yet measured.
- **Risk:** Premature infrastructure and duplicated authorization indexes.
- **Recommended solution:** Establish thresholds for corpus, latency, ranking, and
  operations; extract only when exceeded.
- **Estimated effort:** 8–16 engineer-weeks.
- **Dependencies:** Mature search corpus and benchmarks.
- **Changes architecture documents:** No; retain threshold-based extraction.

## P3.6 Dedicated databases and service extraction

- **Problem:** Present scale does not justify operational distribution.
- **Risk:** Distributed consistency and excessive platform overhead.
- **Recommended solution:** Keep cell-ready contracts; extract by measured scaling,
  security, or team ownership need.
- **Estimated effort:** 15–40+ engineer-weeks per extraction/migration.
- **Dependencies:** Placement abstraction, observability, stable module boundaries.
- **Changes architecture documents:** No after cell-ready revision.

## P3.7 Public ecosystem and certification

- **Problem:** Partner platform ambitions are premature.
- **Risk:** Security exposure and permanent public API commitments.
- **Recommended solution:** Revisit after internal provider SDK, tenant governance, and
  commercial strategy are proven.
- **Estimated effort:** Multi-quarter program.
- **Dependencies:** Partner demand, legal/security program, SDK maturity.
- **Changes architecture documents:** Roadmap timing only.

# Hardening-stage deliverables

The hardening stage is complete only when these reviewed artifacts exist:

1. Revised `ARCHITECTURE.md`, `DOMAIN_MODEL.md`, `ROADMAP.md`, and `DECISIONS.md`.
2. Threat model and mitigation register.
3. Tenancy/database key specification with an executable PostgreSQL prototype.
4. Identity/session and authorization specification with policy test matrix.
5. Connection/provider mirror, capability, conflict, and synchronization specification.
6. Object storage, encryption, classification, retention, and deletion specification.
7. Event/outbox/inbox, idempotency, concurrency, job, and audit specification.
8. AI security and model data-egress specification.
9. Minimum canonical core schema.
10. Architecture fitness-test harness.
11. Phase 1 migration rehearsal report and rollback/forward-fix plan.
12. Approved SLO, RPO, and RTO targets.

No production Phase 2 feature schema should be merged before deliverables 1–10 are
approved. Migration rehearsal and recovery targets must be approved before cutover.

Normative P0 contracts, initial recovery targets, and live evidence status are in
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md). ADR-021 through ADR-032 resolve the
architecture decisions required to begin H0. Executable prototypes, fitness tests, and
rehearsal evidence remain H0 work and must not be represented as complete before their
acceptance records exist.

# Revised Phase 2 implementation sequence

## Stage H0: Architecture hardening

Purpose: validate all P0 contracts and produce their required executable evidence
before production Phase 2 work.

## Stage H1: Platform skeleton

Purpose: establish the production tenancy, identity, authorization, encryption, audit,
and transactional messaging foundation.

## Stage H2: Phase 1 migration foundation

Purpose: move Phase 1 Google capabilities behind provider-neutral connections and
migration boundaries without breaking existing behavior.

## Stage H3: Minimum universal core

Purpose: deliver the constrained universal entity layer and minimum typed operational
core.

## Stage H4: Durable processing and provider synchronization

Purpose: make asynchronous work and provider synchronization durable, recoverable, and
operable.

## Stage H5: Documents, activity, and governed derivation

Purpose: establish governed documents, activity, extraction, provenance, retention, and
derivative deletion.

## Stage H6: Permission-aware search and memory

Purpose: provide permission-aware hybrid search and governed memory.

## Stage H7: Core product and migration cutover

Purpose: deliver core product surfaces and complete the verified Phase 1 cutover.

## Stage H8: Recommendations and basic approvals

Purpose: add evidence-linked recommendations and basic approval-controlled actions
without broad autonomy.

All stage prerequisites, deliverables, required tests, and exit criteria are owned
exclusively by
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#3-canonical-implementation-order).

## Phase 2 completion definition

Phase 2 engineering completion criteria are owned exclusively by
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md). Strategic Phase 2 outcomes are
owned by [ROADMAP.md](ROADMAP.md).
