# Atlas Domain Model

**Owner:** Atlas Domain Council

## 1. Modeling doctrine

Atlas combines:

- a universal identity and relationship layer;
- typed operational aggregates;
- immutable/versioned source documents;
- evidence-backed knowledge;
- governed long-term memory;
- timeline and audit projections.

The universal layer enables connection. Typed aggregates preserve correctness.

The Phase 2 canonical scope, entity allowlist, projection integrity, and tenancy rules
are normative in [H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md). Concepts below that
fall outside this scope describe future modules and do not authorize Phase 2 schema.

## 2. Shared kernel

Stable value types:

- `OrganizationId`, `WorkspaceId`, `UserId`, `MembershipId`
- `EntityId`, `ConnectionId`, `ExternalReference`
- `Actor`, `OwnerRef`, `Permission`
- `Money`, `DateRange`, `Address`, `ContactPoint`
- `EntityVersion`, `CorrelationId`, `CausationId`
- `Classification`, `Visibility`, `RetentionPolicy`

The shared kernel contains no provider SDK or transport types.

## 3. Tenancy and identity

### Organization

Mandatory administrative and legal owner of workspaces. It is a business organization
or a single-member personal organization. Administration does not imply workspace
content access.

### Workspace

Primary data, policy, search, memory, connection, and audit boundary. Contains settings,
locale, time zone, retention, enabled modules, and feature policy.

### User

Global human identity. A user owns no tenant data directly.

### Membership

Connects a user to a workspace with lifecycle status and roles.

### Role and Permission

Roles group capabilities. Permissions express stable operations. Resource policy may
further constrain role permission based on ownership, sensitivity, value, or state.
Phase 2 uses fixed role templates; custom roles are deferred.

### Service Principal and Delegation

Non-human actor and bounded authority grant. Agent delegation records the initiating
human/workspace policy and expiry.

## 4. Universal entity registry

### Entity

Common identity for anything that participates in Atlas-wide capabilities:

- workspace;
- entity type;
- display name;
- lifecycle status;
- owner;
- sensitivity/visibility;
- created/updated/version;
- optional typed projection reference.

Entity types are registered and versioned. They are not arbitrary strings created by
untrusted integrations.

### Entity Relationship

Directed edge with:

- source and target entity;
- relationship type;
- optional inverse type;
- valid-from/valid-to;
- confidence;
- provenance;
- attributes;
- lifecycle status.

Examples:

- person `works_for` company;
- company `owns` property;
- project `has_task` task;
- email `mentions` invoice;
- meeting `concerns` project;
- shipment `uses` vehicle;
- memory `derived_from` document.

### External Reference

Maps a canonical entity to a provider resource:

- workspace;
- connection;
- resource type;
- external ID;
- external version/etag;
- provider timestamps;
- sync state.

Uniqueness is scoped to workspace, connection, resource type, and external ID.

## 5. Generic entity capabilities

### Tags

`Tag` belongs to a workspace. `EntityTag` links tag to entity with actor and timestamp.
Support color, hierarchy, aliases, governance, and future automatic suggestions.

### AI Notes

`Note` targets one or more entities and has author type, body, visibility,
classification, provenance, status, and version. AI-generated notes are marked as AI,
retain evidence, and can be accepted, edited, rejected, or superseded.

### Attachments

`Attachment` links an entity to a document/file entity with purpose, caption, ordering,
and visibility. Content is not duplicated.

### Ownership

Entities may have a responsible membership/team and optional watchers. Ownership does
not replace permission checks.

### Entity permissions

Most access derives from workspace roles. `ResourceGrant` supports exceptional sharing
to users or service principals within the same workspace, with capability, expiry, and
reason. Cross-workspace grants are deferred until separately designed.

## 6. Operational aggregates

Only contacts/persons, companies, projects, tasks, communications/messages,
meetings/calendar events, documents, and provider file placements are part of the
Phase 2 minimum canonical core. Remaining aggregates are future typed modules.

### Contact and Person

Person identity, names, contact points, communication preferences, consent, affiliations,
roles, and source merge state. Provider contacts are references, not canonical identity.

### Company

Legal/trading names, identifiers, addresses, lifecycle, parent/subsidiary relationships,
contacts, commercial roles, and workspace-specific relationship state.

### Project

Objective, scope, status, dates, owner, participants, clients, milestones, budget, risks,
and related entities. Project is workspace-owned; cross-workspace collaboration uses
explicit grants or mirrored references.

### Task

Title, description, state, priority, assignees, due/start dates, dependencies, checklist,
recurrence, estimate, actual effort, source, and parent entity. State changes follow a
defined transition policy.

### Communication

Provider-neutral thread and message model:

- channel: email, Slack, Discord, WhatsApp, Telegram, SMS, internal;
- participants;
- sender;
- timestamps;
- normalized body and attachments;
- provider references;
- delivery/read state;
- thread relationships.

Outbound communication is a command with idempotency, policy, approval, and provider
verification.

### Meeting and Calendar Event

Meeting is the business concept; calendar event is a scheduled provider representation.
A meeting may have several calendar-event references. Includes participants, agenda,
location, recurrence, notes, decisions, and action items.

### Document and File

`Document` is logical content; `DocumentVersion` is immutable source content plus hash,
MIME type, size, storage reference, extraction state, classification, and provenance.
`File` represents placement in a storage provider. One document may have multiple file
placements or versions.

### Asset

**Phase:** Deferred module; not part of the Phase 2 core.

Common asset identity with typed projections for property, vehicle, equipment, product,
and digital asset. Includes ownership, custodian, location, condition, value, lifecycle,
documents, and maintenance.

### Finance

**Phase:** Deferred module; requires a dedicated ledger design and ADR.

Typed aggregates:

- account/counterparty;
- invoice and invoice line;
- payment;
- expense;
- transaction;
- budget;
- tax classification;
- currency/exchange-rate reference.

Finance is not generic JSON. Amounts use decimal plus currency; ledgers require
append-only entries, balancing rules, immutable postings, and strict approvals.

### Shipment

**Phase:** Deferred module; not part of the Phase 2 core.

Origin/destination, parties, status, planned/actual milestones, packages, carrier,
vehicle, documents, cost, exceptions, and tracking references.

### Idea

**Phase:** Deferred module; not part of the Phase 2 core.

Proposal, hypothesis, owner, status, evidence, related entities, evaluation, and
conversion into projects/tasks.

## 7. Source documents and content

### Source

Original evidence such as an email, file version, message, invoice image, transcript, or
provider payload. Includes content hash, collection method, connection, timestamps,
classification, retention, and chain of custody.

### Content Chunk

Versioned extraction unit with offsets/page/section, text, language, extraction method,
content hash, and embedding references.

Documents remain source evidence even when operational records or knowledge are derived.

## 8. Knowledge

### Claim

An atomic statement:

- subject entity;
- predicate;
- object entity or typed literal;
- valid time and observed time;
- confidence;
- status: proposed, verified, disputed, superseded;
- source evidence;
- extraction method/model;
- reviewer.

Contradictory claims coexist until resolved. A resolver may select the currently
preferred claim without deleting history.

Knowledge graph edges are claims or verified entity relationships, not opaque model
output.

## 9. Memory

### Memory Item

AI-retained context with:

- workspace and optional user/project/entity scope;
- type: fact, preference, decision, lesson, summary, pattern, commitment;
- content;
- source references;
- confidence;
- sensitivity;
- visibility;
- valid/expiry times;
- retention;
- supersedes/superseded-by;
- feedback and usage metadata.

Memory can be corrected, forgotten, expired, or promoted from proposed to trusted. It
does not directly mutate operational aggregates.

## 10. Timeline

### Timeline Event

User-facing chronological projection:

- workspace;
- primary and related entities;
- event type;
- title/summary;
- actor;
- occurred/recorded times;
- source/domain event;
- visibility;
- structured attributes.

Timeline examples include email received, meeting completed, task reassigned, invoice
paid, file updated, memory corrected, and recommendation approved.

Timeline is optimized for comprehension and may be rebuilt from domain events. It is
not the security audit log.

## 11. Audit

### Audit Event

Immutable accountability record:

- actor and delegation;
- workspace;
- action;
- target;
- request/correlation;
- authorization decision;
- before/after digest or safe diff;
- source and client metadata;
- outcome/error;
- timestamp;
- approval reference.

Sensitive values are redacted or separately protected. Audit retention is policy-driven
and generally longer than operational event retention.

## 12. Search and embeddings

### Search Document

Permission-aware denormalized representation of an entity, document chunk, knowledge
claim, or memory item. Includes workspace, visibility principals, type, title, body,
structured facets, source version, and indexing status.

### Embedding

Immutable vector record with source object/version, model, dimensions, chunking version,
language, content hash, classification, and timestamp. Re-embedding creates another
version.

Search combines structured filters, full text, vectors, freshness, graph proximity, and
authority. Results return source type, entity, score explanation, and evidence.

## 13. Recommendations

Recommendation aggregate:

- target entities;
- recommendation type;
- proposed command/workflow;
- evidence;
- rationale;
- confidence;
- expected impact;
- risk tier;
- status;
- expiry;
- feedback;
- realized outcome.

Recommendations never execute themselves.

## 14. Agents, workflows, and approvals

### Agent

Versioned role/configuration with allowed tools, domains, policy, prompt/instructions,
model selection, budgets, and evaluation profile.

### Plan

Immutable planned goal, evidence, assumptions, steps, dependencies, risks, and expected
outcomes. Replanning creates a version.

### Workflow Run

Durable state machine with steps, attempts, leases, outputs, errors, compensation, and
correlation.

### Approval Request

Action digest, risk, evidence, requested approvers, policy, expiry, decisions, comments,
and final resolution. Material input change invalidates approval.

### Tool Execution

Command/query name, validated input, effective permission, approval, idempotency key,
provider response reference, verification, cost, latency, and outcome.

## 15. Important state distinctions

- `deleted` is not the same as provider tombstoned.
- `archived` is not deleted.
- `verified claim` is not operational truth until accepted by the owning domain.
- `AI note` is not a human note.
- `recommendation accepted` is not action completed.
- `provider request accepted` is not action verified.
- `memory expired` is not necessarily source deleted.
- `workspace shared` is not public.

These distinctions must be explicit in schemas and state machines.
