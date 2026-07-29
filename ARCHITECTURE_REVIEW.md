# Phase 2 Architecture Review

**Owner:** Atlas CTO

**Reviewer stance:** Incoming CTO, pre-implementation challenge  
**Review date:** 29 July 2026  
**Verdict:** Directionally strong, not yet safe to implement as written

## Executive assessment

The proposed architecture demonstrates good instincts: workspace ownership, provider
ports, typed operational models, provenance, outbox-based events, governed agents, and
an incremental migration. It is substantially better than extending the Phase 1 schema
directly.

It is also too broad, too optimistic about several hard problems, and insufficiently
specific where failure would be catastrophic. It describes nearly every capability a
ten-year platform might need, but does not define enough enforceable constraints for
tenancy, authorization, entity integrity, synchronization ownership, deletion,
financial correctness, event ordering, or AI data governance.

The largest risk is not that Atlas lacks concepts. It is that Atlas has too many
partially designed concepts competing to become foundational.

Do not implement the roadmap verbatim. Narrow the core, resolve the critical decisions
below, and write executable architecture tests before creating Phase 2 tables.

# 1. Strengths

## 1.1 Correct strategic separation

The distinction between operational data, documents, knowledge, memory, timeline, and
audit is essential. Many AI products fail because generated summaries and extracted
facts silently become operational truth.

## 1.2 Workspace-first direction

Moving ownership from users to workspaces is correct. Explicitly preventing automatic
cross-workspace reasoning is one of the strongest decisions in the package.

## 1.3 Provider adapters instead of provider-shaped business logic

Treating Google as an adapter is necessary. The current Phase 1 integration tables and
payloads cannot support Microsoft, IMAP, Dropbox, Slack, Stripe, and Shopify cleanly.

## 1.4 Typed operational domains

Rejecting a universal EAV/JSON database is correct. Tasks, permissions, invoices,
payments, and other critical records require constraints and state machines.

## 1.5 Incremental migration over rewrite

Preserving the operational Phase 1 system is the right business decision. An
expand/backfill/verify/contract approach is safer than rebuilding all integrations.

## 1.6 Agents are not privileged bypasses

Routing agent actions through the same commands, permissions, approvals, and audit path
as humans is non-negotiable and correctly recognized.

## 1.7 PostgreSQL-first operational discipline

Starting with PostgreSQL, pgvector, a transactional outbox, and a modular monolith is
reasonable. It limits infrastructure count while the team learns the real domain.

# 2. Weaknesses

## 2.1 The architecture is a catalog, not yet a system design

The documents name organizations, workspaces, entities, claims, memories, timeline,
events, jobs, workflows, approvals, recommendations, agents, search documents, and
embeddings. They do not consistently define:

- which aggregate owns each invariant;
- transaction boundaries;
- allowed dependency directions at database level;
- source-of-truth rules during provider conflicts;
- required consistency per operation;
- deletion propagation;
- failure behavior under partial provider success;
- volume assumptions and SLOs.

Without those decisions, teams will implement locally reasonable but globally
incompatible interpretations.

## 2.2 “Universal entity” remains dangerously underspecified

The registry-plus-projection approach is better than EAV, but it creates a polymorphic
integrity problem:

- PostgreSQL cannot naturally enforce that an `entity_type=invoice` row has exactly one
  matching invoice projection.
- It cannot prevent one entity from acquiring incompatible projections.
- Deleting a projection can orphan the registry.
- Generic relationships can point to entities in invalid lifecycle states.
- Type renames and projection migrations become global operations.

The design needs an explicit entity creation/deletion protocol, projection registry,
database constraints or triggers, and ownership of display name/status/version.

## 2.3 The core is trying to model too many businesses before learning them

Property, vehicles, shipments, commerce, CRM, finance, messaging, and community
workspaces have different invariants. Designing all projections now will produce
fictional abstractions.

The shared core should initially understand identity, workspace, connection, entity
identity, documents, relationships, activity, permissions, and a small set of proven
domains. The rest should remain modules with explicit maturity gates.

## 2.4 Organization semantics are vague

Organization is described as optional. That creates unresolved questions:

- Who owns a workspace when no organization exists?
- Where do billing, legal ownership, SSO, retention, and data residency live?
- Can a user create organizations?
- Can a workspace move between organizations?
- Does “Personal” have different legal and retention behavior?
- Are organization administrators allowed to access workspace content?

Optional administrative roots tend to become authorization vulnerabilities. Pick one
consistent ownership hierarchy.

## 2.5 Roles and contextual policies are not an authorization design

“RBAC plus contextual policy” is a direction, not a model. Missing details include:

- policy evaluation semantics and precedence;
- explicit deny behavior;
- inherited roles;
- team/group membership;
- object-level grants;
- field-level access;
- guest users;
- support/operator access;
- break-glass access;
- permission caching and revocation latency;
- role template upgrades;
- approval authority versus execution authority;
- agent delegation attenuation.

Custom workspace roles are proposed too early. They multiply migration, support, and
policy-explanation complexity.

## 2.6 Timeline, audit, domain events, and activity risk duplication

The architecture correctly separates them conceptually but gives no storage or
projection strategy to prevent four near-identical high-volume records per change.
Teams will emit inconsistent payloads, timeline rebuilds will become unreliable, and
audit retention costs will grow without bounds.

## 2.7 Knowledge and memory are over-modeled before retrieval quality is proven

Atomic claims with temporal validity, confidence, contradiction, reviewers, source
evidence, and resolution are effectively a knowledge-management product of their own.
This is expensive to build, moderate, evaluate, and explain.

The proposal risks spending a year on ontology infrastructure while users still need
reliable search, tasks, contacts, and briefings.

## 2.8 Finance is acknowledged but not designed

An ADR saying finance is typed and ledger-safe is not enough. Finance requires decisions
about:

- accounting basis;
- chart of accounts;
- journal/posting model;
- reconciliation;
- tax jurisdiction;
- corrections and reversals;
- period close;
- currency conversion;
- invoice/payment matching;
- who is legally responsible for approval.

Atlas should integrate with accounting systems before claiming to be an accounting
system.

# 3. Critical Risks

## 3.1 Critical: shared-schema tenancy can leak data

ADR-014 understates the difficulty of safe row tenancy. One missing `workspace_id`
predicate can expose another company. PostgreSQL RLS helps only if connection context is
set correctly for every transaction and cannot leak through pooled connections,
background jobs, migrations, support tooling, or privileged roles.

### Required redesign now

- Put `workspace_id` in every tenant table primary or candidate key.
- Use composite foreign keys `(workspace_id, parent_id)` so cross-workspace references
  are impossible at the database level.
- Never rely on UUID uniqueness as tenant isolation.
- Define RLS connection-context setup/reset semantics for async pooling.
- Ensure the application role cannot bypass RLS.
- Separate migration, support, and break-glass roles.
- Add automated cross-tenant mutation and inference tests.

**Cost of delay:** Retrofitting composite keys and foreign keys after entities,
relationships, events, and search indexes contain production data is extremely costly.
A single leak could end the company.

## 3.2 Critical: no complete security principal lifecycle

OIDC and MFA are mentioned, but identity linking, session revocation, device/session
management, invitation takeover, email change, account recovery, service accounts,
SCIM, SSO enforcement, and compromised-provider credential response are absent.

**Cost of delay:** Identity identifiers become embedded in audit, approvals, ownership,
and agent delegation. Replacing them later compromises historical accountability.

## 3.3 Critical: credential encryption is deferred

ADR-013 is only a target. Phase 1 uses one Fernet key. Continuing this into multi-tenant
Phase 2 creates a single-key blast radius and no credible rotation procedure.

### Required redesign now

Implement versioned envelope encryption before migrating credentials:

- per-record data encryption keys;
- managed KMS wrapping keys;
- key version recorded with ciphertext;
- rotation and rewrap jobs;
- access audit;
- emergency credential revocation.

**Cost of delay:** Every migrated provider credential must later be decrypted and
rewritten under production load.

## 3.4 Critical: provider synchronization has no conflict authority model

The provider abstraction describes cursors and reconciliation but not who owns fields.
Examples:

- A task generated from an email is edited in Atlas and Microsoft.
- A contact name differs in HubSpot and Google Contacts.
- A file is renamed during an Atlas update.
- A calendar event is changed while an approval is pending.
- Stripe marks a payment settled after Atlas recorded a failure.

Atlas needs per-resource and often per-field authority, version comparison, conflict
states, merge policy, and user-visible resolution. “Last write wins” is unacceptable.

**Cost of delay:** External references and canonical entities will accumulate ambiguous
truth that cannot be repaired automatically.

## 3.5 Critical: deletion and retention are not end-to-end

The architecture mentions retention but does not define a deletion graph across:

- operational rows;
- provider copies;
- documents and versions;
- extracted chunks;
- claims;
- memories;
- embeddings;
- search indexes;
- caches;
- timeline;
- audit;
- backups;
- analytics and model-evaluation datasets.

It also does not resolve legal hold versus user deletion.

**Cost of delay:** Derived data becomes untraceable, making privacy deletion and legal
compliance practically impossible.

## 3.6 Critical: object storage is missing

PostgreSQL and provider files are not a sufficient document architecture. Atlas needs a
defined object store for immutable source snapshots, extracted artifacts, exports, and
quarantine. Provider availability cannot be the only way to reproduce knowledge.

Decide encryption, tenant pathing, content-addressing, retention, malware quarantine,
regional placement, signed access, and backup.

## 3.7 Critical: approvals do not eliminate time-of-check/time-of-use risk

An immutable action digest proves what was approved, not that execution remains safe.
Between approval and execution:

- balances change;
- recipients change identity;
- calendar conflicts appear;
- permissions are revoked;
- provider resources change versions;
- exchange rates change.

Every high-risk command needs execution-time preconditions, version/etag checks,
approval expiry, policy re-evaluation, and possibly renewed approval.

## 3.8 Critical: audit is not tamper-resistant

Writing audit records in the same PostgreSQL database and transaction improves
completeness but not tamper resistance. A database administrator or compromised
application role may alter history.

Define append-only database permissions, hash chaining or signed batches, external
archive/export, clock behavior, redaction rules, and audit verification.

## 3.9 Critical: no threat model for AI data exfiltration

Permission-aware retrieval is necessary but insufficient. Risks include:

- prompt injection in emails and files;
- tool instructions embedded in documents;
- sensitive data entering model-provider logs;
- embeddings leaking semantic information;
- cross-workspace cache contamination;
- agent context over-collection;
- generated exports combining data beyond user intent.

Atlas needs content trust labels, prompt-injection isolation, model data-processing
policies, context minimization, egress classification, and adversarial evaluations.

## 3.10 Critical: no disaster-recovery target

“Backups and restore” is mentioned without RPO, RTO, restore testing, provider
reconciliation after restore, encryption-key recovery, or regional failure strategy.
Ten-year systems fail. Recovery architecture must precede critical business adoption.

# 4. Recommended Changes

## 4.1 Replace ADR-014

**Current:** Shared-schema row tenancy first.

**Replacement:** Cell-ready tenancy with shared-schema deployment initially.

Define a tenant placement abstraction now:

- organization/workspace routing metadata;
- a workspace placement/cell identifier;
- composite tenant keys;
- no cross-cell transaction assumptions;
- export/import tooling contract.

Do not build multiple cells now, but avoid schemas and global sequences that make future
placement impossible.

## 4.2 Amend ADR-003

Limit universal entities to objects that need generic Atlas capabilities. Do not require
every internal row, ledger entry, checklist item, or workflow step to become an entity.

Add:

- entity/projection registration contract;
- transactional factory;
- projection cardinality rules;
- deletion lifecycle;
- type-version migration;
- database integrity tests.

## 4.3 Split ADR-004 into capability and synchronization contracts

One provider abstraction cannot hide all semantic differences. Define:

1. capability contracts for commands and queries;
2. provider resource mirrors preserving provider semantics;
3. canonicalization policies;
4. synchronization/conflict contracts;
5. capability negotiation.

Avoid “lowest common denominator” APIs. A provider adapter may support optional
capabilities with explicit discovery.

## 4.4 Narrow ADR-006

PostgreSQL-first is sensible, but do not make PostgreSQL the object store, job system,
analytics warehouse, search engine, audit archive, and message broker indefinitely.

Define extraction thresholds:

- when jobs move to a durable queue;
- when search moves beyond PostgreSQL;
- when audit gets external archival;
- when timeline/events are partitioned;
- when a workspace gets dedicated placement.

## 4.5 Amend ADR-008

Add event ordering, aggregate sequence numbers, consumer inboxes, schema compatibility,
retention, replay authorization, poison-event handling, backpressure, and privacy
deletion behavior.

Do not imply the outbox itself is an event bus strategy.

## 4.6 Replace ADR-009 with an implementable authorization specification

Before coding, define:

- principal and group model;
- permission vocabulary governance;
- policy language or code-based policy approach;
- deny/allow precedence;
- resource grant semantics;
- support access;
- caching and revocation;
- explainability response;
- authorization test matrix.

Use fixed system roles first. Defer custom role editing.

## 4.7 Amend ADR-010 and ADR-011

Add:

- delegated permission attenuation;
- context and spend budgets;
- runtime policy re-evaluation;
- resource version preconditions;
- approval expiry;
- recipient/account re-verification;
- tool result verification;
- emergency stop;
- immutable execution receipts.

## 4.8 Defer a generalized knowledge graph

Start with:

- entities;
- explicit relationships;
- source documents;
- provenance-backed extracted attributes;
- search.

Introduce general subject-predicate-object claims only after two or three real product
use cases demonstrate the need. This removes a major speculative subsystem.

## 4.9 Define a minimum canonical core

Phase 2 core should initially include only:

- organization/workspace;
- identity/membership/authorization;
- connection and external reference;
- entity identity and relationship;
- contact/company/project/task;
- document/version/attachment;
- activity/timeline;
- audit;
- search document/embedding.

Finance, shipments, properties, vehicles, recommendations, generalized knowledge, and
autonomous workflows should not shape the first schema.

## 4.10 Add architecture fitness tests

Automate checks that:

- domain packages do not import provider/FastAPI/SQLAlchemy SDKs;
- every tenant table has workspace ownership;
- tenant foreign keys are composite;
- every mutation command emits audit/outbox entries;
- cross-workspace reads and writes fail;
- provider adapters pass shared contracts;
- event schemas remain compatible;
- deleted sources disappear from derived indexes.

# 5. Things to Remove

Remove or defer these from the initial Phase 2 implementation:

1. Arbitrary workspace-defined custom roles.
2. General cross-workspace sharing.
3. Generalized temporal knowledge claims and contradiction resolution.
4. Graph-enhanced ranking before baseline hybrid search is measured.
5. Partner integration SDK and certification.
6. Service principals beyond the minimum worker/webhook identities.
7. Organization-wide content access assumptions.
8. Generic finance ledger ambitions.
9. Full agent registry, multi-agent planner, and compensation framework.
10. A universal entity row for every subordinate implementation detail.
11. Optional organization ownership.
12. Premature provider-specific feature parity across all adapters.

Deferral is not rejection. It protects the core from speculative abstractions.

# 6. Things to Add

## 6.1 Data architecture

- Composite tenant foreign keys.
- Object storage and content-addressed document versions.
- Data lineage and derivation graph.
- Schema/version registry for events and canonical provider DTOs.
- Workspace placement/cell abstraction.
- Data-classification propagation rules.
- Deletion/retention dependency graph.
- Backup, restore, export, and workspace migration formats.

## 6.2 Security

- Formal threat model.
- Identity lifecycle and account recovery.
- SSO/SCIM roadmap.
- Break-glass and support-access procedures.
- Envelope encryption implemented, not deferred.
- Signed webhook ingress and replay defense.
- Prompt-injection and AI egress controls.
- Malware scanning and document quarantine.
- Tamper-evident audit archive.
- Security incident credential revocation workflow.

## 6.3 Provider operations

- Field authority and conflict policy.
- Provider resource mirror.
- Sync health/freshness SLO.
- Reconciliation and tombstone semantics.
- Rate-limit budgets and circuit breakers.
- Provider outage behavior.
- Sandbox/test-account strategy.
- Canonical capability conformance tests.

## 6.4 Reliability

- Explicit RPO/RTO.
- Job technology selection and failure semantics.
- Event ordering and replay plan.
- Idempotency key scope and retention.
- Optimistic concurrency on every mutable aggregate.
- Load/volume model.
- Capacity and cost budgets.
- Migration rollback and forward-fix procedures.

## 6.5 Product governance

- Data controller/processor responsibilities per workspace.
- Personal-versus-business privacy policy.
- Workspace export and deletion UX.
- AI source citation and correction workflow.
- Recommendation quality measurement.
- Human escalation and incident handling.

# 7. Priority Matrix

| Priority | Issue | Impact if delayed | Action before implementation |
|---|---|---|---|
| P0 | Tenant keys and cross-tenant integrity | Data breach and irreversible schema debt | Design composite tenant PK/FK strategy |
| P0 | Identity and authorization specification | Account takeover or privilege escalation | Define principals, sessions, roles, policies, revocation |
| P0 | Credential envelope encryption | All provider credentials share one blast radius | Implement KMS/key-version design |
| P0 | Provider conflict/source authority | Canonical data becomes untrustworthy | Define mirror, authority, version, merge states |
| P0 | Deletion and retention lineage | Privacy deletion becomes impossible | Define derivation/deletion graph |
| P0 | Object storage architecture | Source evidence cannot be retained safely | Select and design encrypted object storage |
| P0 | AI threat model | Cross-tenant/sensitive-data exfiltration | Define trust, context, model, and tool boundaries |
| P1 | Entity/projection integrity | Orphaned or contradictory entity graph | Specify lifecycle and enforce constraints |
| P1 | Audit tamper resistance | Weak forensic and compliance evidence | Add append-only roles and external verification |
| P1 | Outbox ordering/replay | Corrupt projections and duplicated effects | Specify sequences, inbox, schemas, poison handling |
| P1 | Job execution semantics | Lost/stuck/duplicated background work | Select durable job model and SLOs |
| P1 | Backup and disaster recovery | Extended outage or unrecoverable loss | Set RPO/RTO and test restore |
| P1 | API idempotency/concurrency | Duplicate external actions and lost updates | Define keys, versions, preconditions |
| P1 | Architecture fitness tests | Boundaries decay immediately | Add automated structural/invariant tests |
| P2 | Search ranking design | Poor relevance and excess complexity | Establish baseline and evaluation corpus |
| P2 | Timeline/event storage volume | Cost and query degradation | Define partitioning and retention |
| P2 | Custom roles | Support and policy complexity | Defer until fixed roles prove insufficient |
| P2 | General knowledge graph | Major speculative investment | Defer to demonstrated use cases |
| P3 | Cross-workspace sharing | Isolation complexity | Exclude from initial Phase 2 |
| P3 | Partner SDK | Premature public contract | Defer until internal adapters stabilize |
| P3 | Multi-agent autonomy | Safety and evaluation burden | Build only after core commands/approvals mature |

# 8. ADR Challenges

## Agree, with conditions

- **ADR-001 Workspace tenancy:** correct, but organization cannot remain optional.
- **ADR-002 Modular monolith:** correct, but Python/package/database boundaries need
  enforcement.
- **ADR-005 Data-plane separation:** correct, but reduce duplicate storage and define
  deletion lineage.
- **ADR-007 Current state plus events:** correct.
- **ADR-012 Hybrid retrieval:** correct direction; graph ranking should be deferred.
- **ADR-015 Document versus file:** correct, but requires object storage.
- **ADR-017 Timeline versus audit:** correct, but storage and retention must differ.
- **ADR-018 No cross-workspace reasoning:** strongly agree.
- **ADR-020 Expand-and-contract:** strongly agree.

## Amend before implementation

- **ADR-003 Universal entities:** constrain scope and specify projection integrity.
- **ADR-004 Provider abstraction:** add mirrors, capability negotiation, and conflict
  semantics.
- **ADR-006 PostgreSQL-first:** define exit thresholds and object storage.
- **ADR-008 Outbox:** specify ordering, schemas, inboxes, replay, and privacy.
- **ADR-010 Agent command parity:** add delegated authority, runtime checks, and emergency
  stop.
- **ADR-011 Action digest:** add time-of-use preconditions and approval expiry.
- **ADR-016 Finance:** redefine Atlas initially as finance integration/workflow, not an
  accounting ledger.
- **ADR-019 Durable jobs:** select concrete semantics before dependent systems.

## Disagree

- **ADR-009 RBAC plus contextual policy as currently stated:** too vague to implement
  safely. Replace with a precise authorization architecture.
- **ADR-013 Encryption as a future target:** unacceptable for Phase 2. It is a P0
  prerequisite.
- **ADR-014 Shared-schema tenancy as stated:** insufficient. Replace with cell-ready,
  composite-key tenancy even if the first deployment remains shared-schema.

# 9. Final CTO Recommendation

Do not begin broad Phase 2 feature implementation.

Approve a short **Architecture Hardening Stage** whose only outputs are:

1. a formal threat model;
2. tenant key and database isolation specification;
3. identity/session/authorization specification;
4. provider mirror, authority, and conflict specification;
5. deletion/retention/lineage specification;
6. object storage and envelope-encryption design;
7. event/job/idempotency/concurrency specification;
8. architecture fitness tests;
9. a revised, smaller canonical core schema;
10. migration rehearsal on a copy of Phase 1 data.

Then implement one thin vertical slice:

```text
authenticated user
→ workspace membership
→ permission check
→ canonical contact entity
→ provider external reference
→ command with optimistic version
→ audit + outbox
→ timeline + search projection
→ cross-tenant denial tests
→ deletion propagation
```

If that slice cannot be made secure, comprehensible, idempotent, observable, and
recoverable, the architecture is not ready for tasks, finance, knowledge graphs, or
agents.

The current design is ambitious enough for ten years, but not yet disciplined enough
for year one. The right correction is not more concepts. It is fewer foundational
concepts with stronger invariants, explicit failure semantics, and executable proof of
isolation.
