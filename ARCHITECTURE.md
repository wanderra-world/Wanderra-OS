# Atlas Technical Architecture

**Owner:** Atlas Architecture Council

## 1. Executive decision

Atlas Core will be a **workspace-first modular monolith with event-driven internals**.
It will use one deployable application and PostgreSQL initially, with strict bounded
contexts, provider ports, an outbox, background workers, and contracts that allow
selected modules to become services later.

The implementable P0 contracts are owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md). Where this overview remains broader,
the approved H0 specification takes precedence.

This is preferable to both extremes:

- A loosely structured monolith would entangle providers, business rules, and AI.
- Premature microservices would add distributed transactions, operational overhead,
  and versioned network contracts before Atlas has stable domain boundaries.

## 2. Architectural invariants

1. Every tenant-owned object has exactly one `workspace_id`.
2. A verified actor and active workspace membership are required before tenant access.
3. Authorization occurs in the application layer before provider or repository calls.
4. Provider payloads never become business-layer contracts.
5. Operational truth uses typed domain models and explicit invariants.
6. Universal entity identity connects domains but does not replace typed records.
7. External data retains provider, connection, external ID, version, and timestamps.
8. Knowledge and memory retain provenance and never silently overwrite operational
   truth.
9. Material mutations produce audit events and domain events in the same transaction.
10. Agent execution uses the same commands, permissions, approvals, and audit path as
    human execution.
11. Search filters authorization before ranking or returning content.
12. Async consumers are idempotent; delivery is at least once, not assumed exactly once.

## 3. System shape

```text
Clients
  Web / Mobile / API / CLI / Provider webhooks
                          |
                    API Gateway Layer
                          |
       Authentication -> Request Context -> Authorization
                          |
                    Application Commands
                          |
  +-----------------------+-------------------------------+
  | Workspace | Entities | Tasks | Projects | Finance    |
  | Contacts  | Comms    | Docs  | Memory   | Agents     |
  +-----------------------+-------------------------------+
            |                  |                 |
       PostgreSQL         Transactional       Provider ports
       + pgvector             outbox                |
            |                  |              Provider adapters
       Search/read models  Event dispatcher    Google/Microsoft/...
                               |
                        Background workers
```

## 4. Bounded contexts

### Identity and Access

Human identities, service principals, sessions, organizations, workspace memberships,
roles, permissions, policy evaluation, invitations, and API credentials.

### Workspace Core

Workspace lifecycle, settings, feature flags, locale, time zone, retention, data
classification, provider policies, and workspace module configuration.

### Entity Registry

Stable entity identity, type, workspace, lifecycle status, ownership, relationships,
tags, attachments, notes, and cross-context references.

### Operational Domains

Typed modules for contacts, companies, projects, tasks, assets, communications,
calendar, documents, finance, property, vehicles, shipments, and future verticals.
Each owns its invariants and tables.

### Connections

Provider accounts, encrypted credentials, OAuth transactions, capability grants,
webhook subscriptions, cursors, synchronization runs, external references, and
provider adapters.

### Knowledge and Memory

Source-derived claims, provenance, confidence, validity, contradictions, summaries,
long-term memories, feedback, sensitivity, retention, and supersession.

### Timeline and Audit

User-visible chronological events and immutable security/compliance audit records.
These are related but deliberately separate.

### Search

Structured filtering, PostgreSQL full-text search, pgvector similarity, graph expansion,
ranking, indexing status, and permission-aware retrieval.

### Automation and Agents

Recommendations, plans, workflow definitions, runs, steps, approvals, budgets,
tool execution, verification, compensation, and outcome evaluation.

## 5. Dependency rule

Dependencies point inward:

```text
API / workers / provider adapters
            ↓
Application commands and queries
            ↓
Domain models and ports
            ↓
Infrastructure implementations
```

Domain modules may depend on shared kernel types such as `WorkspaceId`, `EntityId`,
`Actor`, `Money`, and domain-event interfaces. They must not import FastAPI,
SQLAlchemy models, Google SDK objects, or OpenAI SDK objects.

Cross-module mutation occurs through application commands. Cross-module notification
occurs through domain events. Direct writes into another module's tables are forbidden.

## 6. Workspace and organization architecture

Organizations and workspaces form the tenancy boundary used by every bounded context.
Their canonical business definitions are owned by
[DOMAIN_MODEL.md](DOMAIN_MODEL.md#3-tenancy-and-identity). Their implementable ownership,
database-isolation, placement, and lifecycle contracts are owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#2-tenant-key-and-database-isolation).

## 7. Identity, roles, and permissions

Identity and access is a bounded context used by every command, query, provider call,
and background execution. Canonical identity and permission terminology is owned by
[DOMAIN_MODEL.md](DOMAIN_MODEL.md#3-tenancy-and-identity). Lifecycle and deterministic
authorization contracts are owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#4-identity-and-session-lifecycle) and
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#5-authorization-contract).

## 8. Universal entity architecture

The target system uses a universal identity layer without replacing typed operational
aggregates. The canonical entity and relationship model is owned by
[DOMAIN_MODEL.md](DOMAIN_MODEL.md#4-universal-entity-registry). The Phase 2 allowlist,
projection-integrity rules, and scope constraints are owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#12-universal-entity-and-projection-integrity).

## 9. Operational data, documents, knowledge, memory, and timeline

These are distinct planes:

| Plane | Purpose | Authority |
|---|---|---|
| Operational data | Current business state and workflow | Typed domain module |
| Documents | Original or imported source material | Immutable/versioned content |
| Knowledge | Extracted factual claims | Evidence-backed and correctable |
| Memory | AI-useful retained context | Governed, scoped, confidence-aware |
| Timeline | Chronological business history | Append-oriented event projection |
| Audit | Security/accountability record | Immutable compliance record |

An extracted invoice amount is knowledge until validated or promoted through a domain
command into an operational invoice. An AI summary never silently becomes operational
truth.

## 10. Provider abstraction

### Connections

A connection belongs to one workspace and identifies provider, provider account,
capabilities, status, granted scopes, synchronization policy, and creator. Credentials
are encrypted in a separate table with key versioning.

### Capability ports

Business/application layers use ports such as:

- `EmailProvider`
- `CalendarProvider`
- `StorageProvider`
- `MessagingProvider`
- `CommerceProvider`
- `PaymentProvider`
- `CRMProvider`

Adapters translate provider data into canonical DTOs and translate commands back into
provider operations. Provider-specific extensions stay inside an `extensions` envelope
and never drive core business rules without an explicit capability check.

### Synchronization

Capability ports do not own synchronization semantics. Provider mirrors, authority,
conflicts, and outbound preconditions follow
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#9-provider-mirror-authority-and-conflict-model).

## 11. Event bus and consistency

Bounded contexts communicate after commit through domain events and a transactional
outbox. The event, inbox, ordering, idempotency, concurrency, and replay contract is
owned by [H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#14-event-idempotency-and-concurrency-contract).
The persistence decision and history remain in `DECISIONS.md`.

## 12. Background jobs

Use a durable job system, not FastAPI in-process background tasks, for:

- provider synchronization;
- webhook processing;
- document conversion and extraction;
- embedding generation;
- search indexing;
- knowledge extraction;
- briefings and recommendations;
- workflow and agent steps;
- retention and deletion;
- reconciliation and retries.

Jobs require workspace, type, payload schema version, priority, scheduled time,
attempts, idempotency key, lease/heartbeat, timeout, cancellation, and dead-letter
state. Workers must be horizontally scalable and safe under duplicate delivery.

## 13. Search and embeddings

Use PostgreSQL first:

- typed/structured filters and joins;
- `tsvector` full-text indexes;
- pgvector embeddings with HNSW or IVFFlat as appropriate;
- graph-neighborhood expansion;
- reciprocal-rank or weighted hybrid ranking.

Index permission and workspace metadata. Retrieval must prefilter candidates by
workspace and visibility before content leaves the database. Sensitive content can use
separate indexes or embedding policies.

Embedding records include model, dimensions, content hash, chunking version, language,
created time, and source version. A model migration creates new embeddings alongside
old ones; it does not overwrite them blindly.

Add an external search engine only after measured requirements exceed PostgreSQL.

## 14. Agent architecture

Atlas is a governed application client, not a privileged database user.

Components:

- context builder;
- intent classifier;
- planner;
- specialized domain agents;
- deterministic tool registry;
- policy/risk engine;
- approval coordinator;
- execution engine;
- verifier;
- memory writer;
- outcome evaluator.

Agent plans are structured and versioned. Tools map to application commands/queries and
declare required permission, risk, side effects, reversibility, cost, timeout, and
approval policy.

Risk tiers:

- R0: read-only, low sensitivity;
- R1: reversible internal change;
- R2: external communication or material change;
- R3: financial, permission, deletion, legal, or high-impact action.

Policies determine when an actor can pre-authorize R1/R2 workflows. R3 normally
requires explicit, action-specific approval. Execution records inputs, evidence,
approver, provider response, verification, and compensation status.

## 15. Recommendations and approvals

The recommendation and approval aggregates are owned by
[DOMAIN_MODEL.md](DOMAIN_MODEL.md#13-recommendations). Approval execution rules are
owned by
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#8-approval-rules). Architecture
decisions remain canonical in `DECISIONS.md`.

## 16. API boundaries

Expose versioned REST/JSON initially:

- `/api/v1/workspaces`
- `/api/v1/entities`
- domain routes such as `/projects`, `/tasks`, and `/contacts`;
- `/connections` for provider lifecycle;
- `/search`, `/timeline`, `/memory`, `/recommendations`;
- `/workflows`, `/approvals`, and `/audit`.

Commands and queries use canonical domain schemas. Provider-specific APIs live behind
administrative/debug boundaries, not normal business routes.

Use cursor pagination, idempotency keys for mutations, optimistic concurrency/version
fields, standard error codes, correlation IDs, and OpenAPI contract tests. Webhooks have
provider-specific ingress routes because signatures and delivery semantics differ.

## 17. Security architecture

Security is a cross-cutting architecture boundary rather than a separate business
module. The threat register, identity and authorization controls, encryption, object
custody, deletion lineage, and AI egress requirements are owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#6-threat-model-and-mitigation-register).

## 18. Scalability and operability

Scale in this order:

1. correct indexes and query plans;
2. stateless API replicas;
3. independent worker pools by job class;
4. caching only for measured hot paths;
5. read replicas and connection pooling;
6. table partitioning for timeline/audit/events;
7. workspace placement or database sharding;
8. selective service extraction.

Operational requirements include structured logging, traces, metrics, SLOs, provider
quota dashboards, job lag, sync freshness, dead letters, audit export, migration
observability, and tested backup/restore.

## 19. Migration from Phase 1

Strategic migration outcomes are owned by [ROADMAP.md](ROADMAP.md). Engineering
migration rules are owned by
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#7-migration-rules). H0 rehearsal
evidence and recovery targets are owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#16-migration-and-recovery-targets).
