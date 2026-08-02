# Atlas Platform Status

**Owner:** Atlas Platform Engineering

Last updated: 2 August 2026

## Summary

Atlas is the AI assistant layer of Wanderra OS. The current platform is a Python 3.12
FastAPI service backed by PostgreSQL, with OpenAI-powered chat and durable memory plus
working Google integrations for Gmail, Calendar, and Drive.

The local Docker deployment is operational. The accepted production migration
baseline is `0026_h3_governed_memory`; H3-06 proposes additive revision
`0027_h3_search_context` for review. Formal H0 Exit and Formal H1 Exit are accepted. H1-01
through H1-10 and H2-01 through H2-08 are merged. The H2 platform specification is
accepted. H2-01 through H2-10 are merged and Formal H2 Exit is accepted. PR #24
formally approved the H3 blueprint and opened the sequential implementation gate.
H3-01 Resource Graph is Accepted and merged through PR #26 at `a4602b6`. H3-02 Durable
Execution and Scheduler is Accepted and merged through PR #28 at `915386c`; its
protected required checks passed. H3-03 Documents and Governed Derivation is Accepted
and merged through PR #30 at `3be4480`; its protected required checks passed and
revision `0024_h3_document_custody` established the prior accepted production
migration baseline.
The governance-only H3-04 gate review is merged through PR #31 at `6392d11`. H3-04
Knowledge Service and Timeline is Accepted and merged through PR #32 at `38c326d`;
its protected required checks passed and revision `0025_h3_knowledge_timeline` is the
accepted production migration baseline. H3-05 Memory Manager is Accepted and merged
through PR #34 at `670205d`; its protected required checks passed. H3-06 Search and
Context Assembly is implemented on its dedicated review branch with provider-neutral
full-text/pgvector projections, pre-retrieval ACL enforcement, deterministic hybrid
ranking, graph-bounded filters, safe cited context assembly, durable reindex contracts,
reconciliation, forced RLS, and guarded rollback. Acceptance remains subject to its
dedicated pull request and protected checks.
Gmail/Calendar/Drive authorization has been completed for the current Wanderra user,
and live end-to-end verification has succeeded for email, calendar events, and the
full Drive file lifecycle.

## Implemented capabilities

### H3-06 Search and Context Assembly (pending review)

- Rebuildable, versioned search generations over immutable resource, document,
  knowledge, and memory lineage.
- PostgreSQL full-text and pgvector hybrid retrieval with structured and bounded graph
  filters; exact identifiers retain deterministic priority.
- Workspace/user ACL projections and current resource-state predicates execute in SQL
  before candidates leave PostgreSQL; context assembly reuses only authorized results.
- Cited, classification-preserving, untrusted-data context fragments with a default
  8,192-token/20-fragment ceiling and private-route enforcement for restricted data.
- Idempotent indexing, source disposition, derivative reconciliation, old/new index
  coexistence, lexical fallback, audit/outbox evidence, and H3-02 durable reindex and
  cleanup commands.
- Additive `0027_h3_search_context` migration with forced RLS and guarded populated
  downgrade. No Phase 1 API or previous H-layer runtime behavior changes.

### Atlas Core H1-01

- Primary placement cell metadata.
- Mandatory business or personal organization records.
- Organization ownership records with deferred last-owner enforcement.
- Workspace records with immutable organization ownership during Phase 2.
- Forced workspace RLS on workspaces, audit events, and outbox events.
- Deterministic default personal organization/workspace backfill for existing Phase 1
  users.
- Immutable workspace-creation audit records and transactional outbox records.
- Fully reversible additive migration; Phase 1 tables and runtime routes are unchanged.

### Atlas Core H1-02

- Canonical global `User` model owned by the Identity bounded context.
- Lifecycle status, verification provenance, timestamps, and optimistic version.
- External identity links unique by issuer and subject.
- Duplicate verified email addresses remain distinct identities and never merge
  automatically.
- Existing Phase 1 user UUIDs and Gmail, Calendar, Drive, project, and conversation
  foreign keys are preserved.
- Atomic identity-migration audit and outbox evidence.
- Safe downgrade when no external links or duplicate emails exist; otherwise the
  migration requires an explicit reviewed forward fix.
- No session, invitation, recovery, MFA, membership, permission, or login behavior.

### Atlas Core H1-03

- Opaque server-side sessions persisted only as SHA-256 token hashes.
- Device, authentication-strength, recent-MFA, expiry, last-seen, and revocation
  state.
- Hashed, scoped, expiring, single-use invitation and recovery tokens.
- Row-lock concurrency protection against token replay.
- Atomic account recovery that revokes sessions and remaining recovery material.
- Reversible external-identity linking review with recent strong-authentication
  evidence.
- Durable security notifications plus transactional audit and outbox records.
- Secure host-only cookie policy and constant-time double-submit CSRF validation.
- Additive forced-RLS schema with guarded downgrade and no Phase 1 runtime wiring.

### Atlas Core H1-04

- Canonical membership records linking a user, organization, and workspace through
  composite tenant keys.
- Deterministic, versioned organization and workspace role classifications without
  capability mappings or policy evaluation.
- Invited, active, suspended, and revoked membership lifecycle.
- Single-use H1-03 invitation-token acceptance linked to the resulting membership.
- Immediate role and lifecycle version changes with transactional audit/outbox events.
- Deferred database invariants preserving an active workspace owner and personal
  organization consistency.
- Forced workspace RLS and repository methods that retain explicit workspace scope.
- Guarded rollback that refuses to discard post-migration membership state.
- No API, authorization engine, provider, agent, search, or memory changes.

### Atlas Core H1-05

- The H1-04 fixed system-role table is reused as the canonical Role model.
- H1-04 workspace memberships remain the canonical role assignments.
- Versioned canonical permission definitions and explicit fixed-role allow/deny rules.
- Uncached workspace-scoped permission lookup with explicit-deny precedence.
- Deny-first checks for workspace mismatch and invalid actor, session, or membership.
- Stable versioned authorization decisions and reason codes.
- Redacted transactional audit and outbox records for allow and deny decisions.
- Forced-RLS membership joins that cannot expose cross-workspace assignments.
- Guarded rollback that refuses to remove mutated catalogs or recorded decisions.
- No custom roles, inheritance, ABAC, APIs, provider access, agents, workflows,
  notifications, search, memory, or H1-06 context plumbing.

### Atlas Core H1-06

- Immutable, versioned request, actor, tenant, delegation, and correlation context.
- Request-scoped context binding with nested-scope isolation and guaranteed reset.
- Placement validation against canonical Organization, Workspace, and Cell records.
- Transaction-local PostgreSQL workspace, actor, session, membership, authorization
  decision, request, and correlation settings.
- Context-required repository base contract that rejects missing, mismatched, and
  cross-workspace execution.
- Safe audit/outbox trace references without session or membership identifier leakage.
- Forced-RLS validation under non-owner, non-bypass runtime roles.
- Pool reuse and deterministic replay tests proving context never leaks between
  transactions.
- Schema-free delivery with H1-05 downgrade/upgrade rehearsal; production remains at
  migration `0010_h1_authorization`.
- No Phase 1 route wiring, authorization changes, policy changes, providers, agents,
  jobs, workflows, notifications, search, memory, or H1-07 functionality.

### Atlas Core H1-07

- Versioned AES-256-GCM per-record envelope encryption with independently wrapped
  data-encryption keys.
- Tenant, connection, record-type, record-ID, and format-version authenticated data.
- Narrow asynchronous managed-KMS port and Google Cloud KMS production adapter.
- Immutable managed-key resource/version references with fail-closed provider errors.
- Context-bound envelope repository and forced workspace RLS.
- Idempotent KEK rewrap and DEK replacement with durable rotation checkpoints.
- Wrong-version, corrupted-ciphertext, provider-outage, and emergency-disable denial.
- Failure quarantine and redacted transactional audit/outbox evidence.
- Additive Gmail, Calendar, and Drive credential shadow columns; legacy ciphertext
  remains untouched and continues serving all Phase 1 runtime reads.
- Shadow equivalence verification, legacy checksums, explicit cutover state, and
  reauthorization fallback metadata.
- Guarded rollback that preserves legacy provider access and refuses to discard
  envelope migration state.
- No connection unification, provider runtime changes, agents, workflows, scheduler,
  jobs, notifications, search, memory, or H1-08 functionality.

### Atlas Core H1-08

- Append-only canonical audit writer with redacted, decision-linked records.
- Per-workspace SHA-256 audit chains, checkpoints, and verification.
- Caller-owned command idempotency and optimistic aggregate versions.
- Transactional canonical outbox writes that commit atomically with audit and
  idempotency evidence.
- Inbox deduplication, per-aggregate consumer sequencing, gap and poison-message
  quarantine, and explicit authorized replay.
- Versioned event contracts with unsupported-schema quarantine.
- Forced workspace RLS for all new messaging state.
- Retention and partition-readiness metadata without selecting a partitioning system.
- Additive, rehearsed migration with guarded rollback after H1-08 state is created.
- No broker, worker, scheduler, provider effects, timeline, memory, search, or H1-09
  functionality.

### Atlas Core H1-09

- Managed-key AES-256-GCM encryption for PostgreSQL backup artifacts.
- Fail-closed KMS recovery and authenticated backup integrity verification.
- Isolated restore evidence with exact H1 row-count and digest comparison.
- Instrumented 15-minute PostgreSQL RPO and four-hour core RTO targets.
- Versioned, idempotent synthetic export manifests limited to H1-owned workspace data.
- Explicitly authorized workspace closure with immediate access revocation and
  ordinary H1 write freezing.
- Legal-hold and minimum-retention precedence over erasure.
- Eligible H1 session, token, notification, encryption, command, inbox, consumer, and
  quarantine erasure.
- Immutable closure receipts, recovery evidence, and export manifests.
- Explicit preservation of Phase 1 provider data with provider reconciliation recorded
  as an H2 dependency.
- Additive migration, forced RLS, rollback rehearsal, and guarded forward-fix behavior.
- No provider deletion, document lineage, content export, workspace transfer, cell
  migration, or H1-10 functionality.

### H1-10 Formal Exit

- Added an integrated two-tenant acceptance harness covering isolation, session
  revocation, deterministic authorization, execution context, audit integrity,
  messaging idempotency, encrypted backup and restore, closure, and deletion.
- Added the H1 evidence matrix and security review without changing the architecture,
  ADRs, roadmap, production schema, or previously accepted slice contracts.
- Pull request #11 is merged, all mandatory checks passed, and Formal H1 Exit is
  accepted.
- At Formal H1 Exit, H2 had not started; H2-01 began only after H1 acceptance.

### Atlas Core H2-01

- Stable provider registry metadata without provider behavior in the business layer.
- Canonical workspace-owned connections bound to exact organization, workspace, and
  placement-cell coordinates.
- Pending, active, degraded, reauthorization-required, revoked, and closed lifecycle
  with deterministic transition rules and optimistic concurrency.
- Versioned provider-neutral connection kinds and capability grants.
- Non-secret granted-scope metadata.
- H1 `manage_workspace` authorization for creation and material lifecycle changes.
- Context-bound repository and forced PostgreSQL RLS for all tenant-owned H2-01 tables.
- Composite tenant placement keys, workspace-scoped provider-account uniqueness, and
  immutable connection identity.
- Atomic immutable audit and transactional outbox evidence.
- Additive migration with empty/populated/repeated upgrade, safe rollback, and guarded
  forward-fix evidence.
- No credential, OAuth, mirror, provider client, route, API, backfill, cutover, or
  H2-02 functionality.

### Atlas Core H2-02

- Provider-neutral connection credential metadata references the accepted H1 managed
  encrypted-envelope boundary.
- Authenticated encryption context binds workspace, connection, provider, credential
  kind, record identity, format, and credential generation.
- Deterministic Phase 1 inventory records row identity, ciphertext checksum, normalized
  scope inventory, eligibility, attempts, exceptions, and verification state.
- PostgreSQL advisory transaction locks and source uniqueness make concurrent shadow
  migration idempotent, resumable, and replay safe.
- Canonical JSON comparison proves semantic equivalence before a shadow is marked
  verified.
- Rotation, revocation, reauthorization-required, expiry metadata, and emergency
  disable states are transactionally audited and emitted through the outbox.
- Forced PostgreSQL RLS, composite tenant foreign keys, immutable envelope context,
  workspace write freezing, and guarded rollback protect custody metadata.
- The migration-only Phase 1 linker writes envelope checksum and verification evidence
  while leaving legacy ciphertext and `envelope_cutover = false`.
- No OAuth transaction, callback routing, provider capability, adapter execution,
  mirror, API, cutover, or H2-03 functionality is present.

### Atlas Core H2-03

- Canonical, provider-neutral, workspace-owned, one-time OAuth transaction metadata.
- Raw state and PKCE verifier material exists only inside an H1 managed encrypted
  envelope; database metadata, representations, audit, and outbox records are
  secret-free.
- State is workspace-routable without legacy provider-table probing and is persisted
  only as a SHA-256 digest.
- Redirect, issuer, provider, purpose, actor, session, membership, authorization
  decision, expiry, and connection bindings fail closed.
- Incremental scope supersets are accepted when all required scopes are present and
  every returned scope is allowed.
- PostgreSQL row locks and terminal-state immutability make callback consumption
  single-use and concurrency safe.
- Provider exchange and H2-02 custody are narrow asynchronous ports; no provider SDK
  or provider business operation enters the core boundary.
- Forced PostgreSQL RLS, closed-workspace write protection, immutable binding
  metadata, additive migration, and guarded rollback protect transaction evidence.
- Phase 1 Gmail, Calendar, Drive, their registered callback URL, and legacy state
  tables remain unchanged.
- No provider mirror, external reference, capability execution, adapter cutover,
  worker, API, or H2-04 functionality is present.

### Atlas Core H2-04

- Canonical workspace- and connection-scoped provider mirrors with stable external
  resource identity.
- Immutable external-reference identity with an approval-linked optional future
  canonical reference; no H3 universal entity is introduced.
- Explicit resource and field authority metadata using the four accepted authority
  policies.
- Deterministic inbound comparison decisions for no-change, provider-authoritative
  application, conflict, and tombstone outcomes.
- Deterministic outbound precondition decisions that deny provider-authoritative
  writes and require refresh instead of blind stale retries.
- Durable comparison evidence and PostgreSQL advisory locks make observation and
  decision replay idempotent.
- Explicit conflict evidence and user-resolution records prohibit destructive
  last-write-wins behavior.
- Provider tombstones preserve governed Atlas evidence and remain distinct from Atlas
  deletion.
- Optional raw-payload references require an approved custody owner; H2-04 stores no
  raw provider payload blobs.
- Forced PostgreSQL RLS, composite workspace foreign keys, immutable identity
  triggers, audit/outbox atomicity, additive migration, and guarded rollback protect
  mirror state.
- No provider call, capability port, adapter, webhook, poller, scheduler, worker,
  universal entity, automatic conflict resolution, API, or H2-05 functionality is
  present.

### Atlas Core H2-05

- Immutable provider-neutral email, calendar, and storage DTOs cover every approved
  Phase 1 operation.
- Asynchronous canonical ports isolate application code from concrete provider SDK
  clients, resources, exceptions, field names, and payloads.
- Deterministic capability discovery and exact-version negotiation avoid
  provider-name branching.
- Canonical errors distinguish authentication, authorization, scope, rate limit,
  transient, conflict, not found, invalid input, quota, and unsupported capability.
- Opaque cursors, offset-preserving timestamps, version preconditions, mutation
  idempotency contexts, and namespaced non-authoritative extensions are explicit.
- A deterministic in-memory second provider passes the shared email, calendar, and
  storage conformance suite.
- Static fitness tests prohibit SDK leakage, runtime framework/database coupling,
  provider-name conditionals, and H2-06+ concepts.
- H2-05 is schema-free and runtime-disconnected. Phase 1 APIs, Google integrations,
  H2 connection/OAuth/mirror behavior, and production migration revision remain
  unchanged.
- No production adapter, provider call, synchronization, shadow routing, cutover,
  webhook, worker, or H2-06 functionality is present.

### Atlas Core H2-06

- The production Gmail adapter implements the canonical H2-05 email port and
  translates profiles, message pages, unread and query searches, drafts, sends,
  cursors, timestamps, versions, and namespaced extensions.
- Google SDK resources, payloads, and exceptions are confined to the adapter and
  normalized into canonical DTOs and safe error categories.
- Managed connection credentials are loaded through the H2-02 credential repository
  and H1 envelope encryption only after workspace authorization.
- Per-workspace connection routing supports legacy, shadow, and canonical modes;
  shadow reads return the legacy result while recording deterministic equivalence.
- Disabling the canonical route immediately restores the Phase 1 path without
  changing credentials or duplicating provider effects.
- Send requires an explicit approval reference and caller-owned idempotency; shadow
  mode never performs dual writes, and the adapter re-reads the provider result.
- Route changes are authorization-gated and emit transactional audit and outbox
  evidence.
- Additive routing and shadow-evidence tables use composite workspace keys, forced
  RLS, immutable comparison evidence, and guarded rollback.
- Phase 1 APIs remain unchanged. No continuous synchronization, webhook, polling,
  worker, Calendar adapter, Drive adapter, or H2-07+ functionality is present.

### Atlas Core H2-07

- The production Google Calendar adapter implements the canonical H2-05 Calendar port
  for event listing, creation, update, and deletion.
- Timed offsets, IANA timezone annotations, all-day dates, recurrence rules,
  attendees, provider versions, cursors, and namespaced extensions are translated
  without provider types escaping the adapter.
- Managed credentials reuse the H2-02 repository and H1 envelope service after
  authorization; the shared loader also removes duplicate credential plumbing from
  the accepted email adapter without changing its behavior.
- Per-workspace connection routing supports legacy, shadow, and canonical modes.
  Shadow reads return the legacy result and append deterministic comparison evidence.
- Create, update, and delete require action-specific approval and caller-owned
  idempotency. Update/delete require provider version preconditions and never blind
  retry conflicts.
- Mutations perform provider read-back or absence verification before returning.
- Authorized route changes emit transactional audit and outbox evidence.
- Additive Calendar routing and shadow-evidence tables use composite workspace keys,
  forced RLS, immutable comparisons, and guarded rollback.
- Phase 1 Calendar APIs remain unchanged. No continuous synchronization, push
  notification, scheduler, worker, storage adapter, or H2-08+ behavior is present.

### Atlas Core H2-08

- Canonical Drive list, search, metadata, download, upload, update, delete, and text
  projection behavior behind the H2-05 storage port.
- Google Docs, PDF, and DOCX readable-text paths remain transient; binary content is
  not copied into PostgreSQL.
- Managed credentials, provider observation, safe errors, opaque cursors, checksums,
  versions, approval, idempotency, post-write verification, and rollback are explicit.
- Legacy, shadow, and canonical workspace routes use additive forced-RLS state and
  immutable comparison evidence.
- Phase 1 APIs remain unchanged.

### Atlas Core H2-09

- Deterministic and restartable default-workspace connection backfill combines each
  Google Workspace provider account without merging unrelated accounts.
- Immutable source and reconciliation checksums detect changed or ambiguous replays.
- Explicit reauthorization exceptions preserve valid Phase 1 credential fallback.
- Read routing requires evidence-backed legacy → shadow → canonical cutover. Mutation
  routing remains independently controlled and defaults to legacy.
- Canonical routing requires configured sample and failure-budget thresholds; rollback
  to the legacy path is always available.
- H2-owned state is included in recovery/export manifests and closure disables
  credentials, closes connections, restores legacy flags, and preserves provider
  reconciliation boundaries.
- Compatibility code remains owned by Atlas Core until the explicit H7 removal gate.

### Atlas Core H2-10

- Integrated canonical-output validation covers Gmail, Google Calendar, and Google
  Drive through the provider-neutral H2 capability ports.
- Two independent deterministic mock-provider connections prove shared email,
  calendar, and storage contracts are not Google-shaped.
- Adversarial replay and stale-version mutation tests fail closed.
- A complete H2 evidence matrix and formal security review trace migration, RLS,
  routing, cutover, rollback, approval, recovery, export, closure, and compatibility.
- H2-10 is schema-free and changes no production runtime behavior. PR #23 passed the
  protected required gate, merged into `master`, and made Formal H2 Exit effective.
- At H2-10 acceptance, H3 production implementation had not started.

### H3-02 Durable Execution and Scheduler

- Versioned provider-neutral job definitions, instances, attempts, leases,
  heartbeats, retry taxonomy, deadlines, cancellation, dead letters, and replay.
- Caller-owned idempotency with changed-input denial and concurrency-safe PostgreSQL
  advisory locking.
- One-time, interval, and daily-local schedules with explicit misfire and DST policy.
- Workspace/definition pause controls, bounded concurrency, rate/backlog quotas,
  organization capacity, deterministic tenant-fair ordering, and backpressure.
- Context-bound repository and service layers with forced RLS, composite tenant keys,
  H1 authorization, audit, and transactional outbox evidence.
- Generic typed job-handler and deployable worker boundary with Docker smoke coverage.
- Additive revision `0023_h3_durable_execution` with empty rollback and guarded
  forward-fix/export after durable state exists.
- No API or Phase 1 behavior change and no H3-03+ or business-agent functionality.

### H3-03 Documents and Governed Derivation

- Canonical workspace-scoped documents, immutable content-addressed versions,
  derivatives, chunks, and durable deletion records.
- Quarantine-first custody with SHA-256 substitution detection, MIME verification,
  malware evidence, explicit promotion, and fail-closed extraction gates.
- Monotonic classification, versioned policy and encryption-key lineage, legal holds,
  retention precedence, recovery manifests, and restore-integrity verification.
- Provider-neutral object-storage, verifier, extractor, extraction-job, and
  deletion-job ports; no provider SDK or business-agent dependency.
- Deterministic extraction replay and source-linked chunks executed through the
  accepted H3-02 durable-job boundary.
- Two-phase deletion with revalidated policy, retryable exception evidence,
  idempotent object cleanup, and PostgreSQL content redaction.
- Context-bound repository and service layers with H1 authorization, forced RLS,
  composite tenant keys, audit evidence, and transactional outbox events.
- Additive revision `0024_h3_document_custody` with empty rollback and guarded
  forward-fix/export after custody state exists.
- No API or Phase 1 behavior change and no H3-04+, knowledge, memory, search, or
  business-agent functionality.

### H3-04 Knowledge Service and Timeline

- Typed, evidence-backed claims with canonical identity, deterministic derivation
  replay, confidence, validity, extraction provenance, review state, and immutable
  H3-03 source spans.
- Explicit contradiction and supersession relationships; knowledge never mutates
  operational truth.
- Classification monotonicity and retrieval-time source custody revalidation.
- Deterministic, idempotent timeline projection, ordering, visibility, replay,
  removal, rebuild, and checksums without copying or replacing H1 audit evidence.
- Durable H3-02 source-disposition jobs with idempotent invalidation and timeline
  propagation evidence.
- Context-bound repository and service layers with H1 authorization, forced RLS,
  composite tenant keys, audit evidence, and transactional outbox events.
- Additive revision `0025_h3_knowledge_timeline` with empty rollback and guarded
  forward-fix/export after knowledge or timeline state exists.
- No API or Phase 1 behavior change and no H3-05+, memory, search, provider-specific,
  H4, or business-agent functionality.

### H3-05 Memory Manager (Accepted)

- Provider-neutral governed memory items remain distinct from operational truth,
  evidence-backed knowledge, source documents, timeline projections, and legacy
  Phase 1 retrieval memory.
- Typed provenance binds every item to current H3-01 resources, H3-03 document
  versions, H3-04 claims, or governed-memory inputs; retrieval revalidates source
  version and digest custody.
- Deterministic identity replay, versioned consolidation, confidence, monotonic
  classification, visibility, human confirmation, durable feedback, pinning,
  expiry, supersession, deletion, and transitive source invalidation.
- Restricted-memory model egress fails closed unless the approved private route is
  selected; private memories are owner constrained.
- Context-bound repository and service layers reuse H1 authorization and execution
  context, forced RLS, composite tenant keys, audit evidence, and transactional
  outbox events.
- Additive revision `0026_h3_governed_memory` supports empty rollback and guarded
  forward-fix/export after governed-memory state exists.
- No HTTP API, Phase 1 behavior change, search, embeddings, recommendations,
  provider-specific behavior, H3-06+, H4, or business-agent functionality.

### Atlas and memory

- Atlas chat endpoint backed by the configured OpenAI model.
- User, project, conversation, and conversation-message persistence.
- Embedding generation and cosine-similarity memory search.
- External-source identity fields for deduplicating imported messages.

### Gmail

- PKCE OAuth with encrypted refresh-token persistence.
- Incremental Google authorization compatible with Calendar and Drive grants.
- List recent messages, list unread messages, and Gmail-query search.
- Create drafts and send email.
- MIME generation and plain-text message parsing.
- Imported and sent messages are written to Atlas memory once per Gmail message ID.
- Live verification completed against `wanderra.world@gmail.com`.

### Google Calendar

- PKCE OAuth using the existing Google client and registered callback.
- List upcoming events.
- Create, update, and delete events.
- Timed and all-day event request support, including explicit time zones.
- Live create/update/delete lifecycle verified on the primary calendar.

### Google Drive

- Incremental PKCE OAuth that preserves the existing Gmail and Calendar scope grants.
- List and text-search files.
- Read file metadata.
- Download binary files and export Google Docs as plain text.
- Multipart upload.
- Update file metadata and replace file content.
- Delete files.
- Extract readable text from Google Docs, PDF, and DOCX.
- Synchronize observed file metadata into PostgreSQL on list, search, metadata read,
  download, upload, and update; remove the metadata row on deletion.
- Live reversible end-to-end verification completed for TXT, PDF, and DOCX, including
  cleanup in Drive and PostgreSQL.

## Architecture

```text
Client
  |
  | HTTP + X-User-ID
  v
FastAPI /api/v1
  |-- Atlas chat
  |-- Gmail service -------- Google Gmail API
  |-- Calendar service ----- Google Calendar API
  |-- Drive service -------- Google Drive API
  |
  |-- shared Google OAuth callback and scope validation
  |-- Fernet-encrypted provider credentials
  v
PostgreSQL
  |-- Atlas users/projects/conversations/memory
  |-- OAuth state and encrypted credentials per integration
  |-- synchronized Drive metadata
  `-- H1 organization/workspace placement, audit, and outbox foundation
```

The three Google integrations reuse one OAuth client configuration and the callback
registered at `/api/v1/gmail/oauth/callback`. A database-backed state value dispatches
the callback to Gmail, Calendar, or Drive. PKCE verifiers are persisted for the short
authorization window. Returned incremental scope sets are accepted only when they
contain the required integration scope and are a subset of the explicitly allowed
Gmail, Calendar, and Drive scopes.

Credentials are encrypted at rest with Fernet using
`GMAIL_CREDENTIALS_ENCRYPTION_KEY`. Google client secrets are mounted read-only into
the API container from `secrets/google`.

The Docker Compose stack contains:

- `api`: FastAPI/Uvicorn service on port 8000; applies Alembic migrations at startup.
- `db`: PostgreSQL 16 with a persistent named volume.

## Database schema

| Table | Purpose |
|---|---|
| `users` | Wanderra user identity and profile fields |
| `projects` | User-owned project records |
| `conversations` | User/project conversation containers |
| `conversation_messages` | Messages, embeddings, and optional external-source identity |
| `gmail_credentials` | Encrypted per-user Gmail credential |
| `gmail_oauth_states` | Expiring Gmail OAuth state and PKCE verifier |
| `calendar_credentials` | Encrypted per-user Calendar credential |
| `calendar_oauth_states` | Expiring Calendar OAuth state and PKCE verifier |
| `drive_credentials` | Encrypted per-user Drive credential |
| `drive_oauth_states` | Expiring Drive OAuth state and PKCE verifier |
| `drive_file_metadata` | Per-user cached Drive metadata keyed by Google file ID |
| `cells` | Workspace placement targets; H1 currently seeds one primary cell |
| `organizations` | Mandatory business or personal workspace owner |
| `organization_memberships` | Administrative owners and administrators; no implicit workspace access |
| `workspaces` | Primary tenant boundary with organization and cell placement |
| `audit_events` | Immutable workspace-scoped accountability records |
| `outbox_events` | Workspace-scoped transactional domain-event records |
| `external_identity_links` | Canonical login identities keyed by issuer and subject |
| `provider_registry` | Versioned provider identifiers and family metadata |
| `connection_kinds` | Versioned provider-neutral connection-kind definitions |
| `provider_capabilities` | Versioned capability identifiers |
| `connection_kind_capabilities` | Capabilities allowed for each connection kind |
| `connections` | Canonical workspace-owned provider account connections |
| `connection_capability_grants` | Workspace-owned versioned connection capability grants |
| `connection_credentials` | Connection-bound encrypted credential generation metadata |
| `credential_migration_inventory` | Idempotent Phase 1 credential inventory and shadow-verification evidence |
| `oauth_transactions` | Workspace-bound, single-use canonical OAuth transaction metadata |
| `provider_mirrors` | Provider resource identity, authority, version, hash, state, and tombstone metadata |
| `provider_external_references` | Immutable provider identity and optional approved canonical linkage |
| `provider_mirror_conflicts` | Explicit conflict detection and user-resolution evidence |
| `provider_mirror_comparisons` | Idempotent inbound and outbound comparison decisions |
| `resource_projections` | One-to-one typed operational projection bindings |
| `resources` | Constrained, versioned, connectable resource identities |
| `resource_relationships` | Typed, directed, workspace-safe resource relationships |
| `resource_tags` | Normalized shared resource tags |
| `resource_attachments` | Resource-to-document attachment references |
| `resource_notes` | Human and provenance-bearing AI notes |
| `resource_ownerships` | Explicit resource ownership assignments |
| `resource_grants` | Exceptional resource-scoped permission grants |
| `resource_external_links` | Immutable links to H2 provider external references |
| `job_definitions` | Versioned handler, retry, concurrency, and rate contracts |
| `job_instances` | Durable command eligibility, lifecycle, lease, deadline, and replay state |
| `job_attempts` | Immutable attempt and heartbeat outcome evidence |
| `job_dead_letters` | Terminal failure and authorized replay evidence |
| `job_schedules` | One-time and recurring time-eligibility definitions |
| `job_operator_controls` | Audited workspace and definition pause/resume state |
| `documents` | Workspace-owned logical documents linked to typed resources |
| `document_versions` | Immutable content-addressed custody versions |
| `document_derivatives` | Versioned processor outputs with source lineage |
| `document_chunks` | Classified source-linked governed text chunks |
| `document_deletions` | Durable deletion, hold, retention, and exception evidence |
| `knowledge_claims` | Typed evidence-backed claims distinct from operational truth |
| `knowledge_evidence` | Immutable H3-03 source-version and source-span lineage |
| `knowledge_relations` | Explicit contradiction and supersession evidence |
| `knowledge_source_dispositions` | Durable source invalidation propagation state |
| `timeline_entries` | Rebuildable user-facing activity projection |
| `timeline_checkpoints` | Deterministic timeline rebuild checksums and cursors |

`drive_file_metadata` stores the file name, MIME type, size, modification time, view
link, MD5 checksum, parent IDs, the normalized provider payload, and synchronization
time. Deleting a file through Atlas also deletes its metadata row.

## API endpoints

All versioned endpoints use the `/api/v1` prefix. Integration routes require an
`X-User-ID` UUID header unless noted otherwise.

### Platform

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service liveness and environment |
| `POST` | `/api/v1/atlas/chat` | Send a message to Atlas |

### Gmail

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/gmail/oauth/authorize` | Start Gmail authorization |
| `GET` | `/api/v1/gmail/oauth/callback` | Shared Google OAuth callback |
| `GET` | `/api/v1/gmail/messages` | List recent messages |
| `GET` | `/api/v1/gmail/unread` | List unread messages |
| `GET` | `/api/v1/gmail/search` | Search using a Gmail query |
| `POST` | `/api/v1/gmail/draft` | Create a draft |
| `POST` | `/api/v1/gmail/send` | Send an email |

### Calendar

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/calendar/oauth/authorize` | Start Calendar authorization |
| `GET` | `/api/v1/calendar/events` | List ordered events |
| `POST` | `/api/v1/calendar/events` | Create an event |
| `PATCH` | `/api/v1/calendar/events/{event_id}` | Update an event |
| `DELETE` | `/api/v1/calendar/events/{event_id}` | Delete an event |

### Drive

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/drive/oauth/authorize` | Start Drive authorization |
| `GET` | `/api/v1/drive/files` | List files with pagination |
| `GET` | `/api/v1/drive/search` | Search names and indexed text |
| `GET` | `/api/v1/drive/files/{file_id}/metadata` | Read file metadata |
| `GET` | `/api/v1/drive/files/{file_id}/content` | Download/export content |
| `GET` | `/api/v1/drive/files/{file_id}/text` | Extract Google Docs/PDF/DOCX text |
| `POST` | `/api/v1/drive/files` | Upload a file |
| `PATCH` | `/api/v1/drive/files/{file_id}` | Update metadata |
| `PUT` | `/api/v1/drive/files/{file_id}/content` | Replace binary content |
| `DELETE` | `/api/v1/drive/files/{file_id}` | Delete a file |

Interactive OpenAPI documentation is available at `/docs`.

## Test coverage

The current PostgreSQL-backed automated suite contains 554 passing tests:

- Health and Atlas chat API behavior.
- Gmail MIME construction and message parsing.
- Calendar request serialization, time validation, update validation, and response
  projection.
- Incremental Google OAuth acceptance for Gmail, Calendar, and Drive, plus rejection
  of missing or unexpected scopes.
- Drive search escaping and metadata normalization.
- Drive MIME dispatch regression coverage.
- H3-01 constrained resource/projection identity, typed relationships, shared resource
  capabilities, optimistic concurrency, audit/outbox, external-reference linkage,
  forced RLS, migration, rollback, and cross-workspace isolation.
- H3-02 typed job and retry contracts, idempotent enqueue, attempts, leases,
  heartbeat/crash recovery, deadlines, cancellation, dead letters, authorized replay,
  misfire and DST behavior, pause controls, quotas, tenant fairness, concurrent claim,
  forced RLS, migration, guarded rollback, worker conformance, and architecture scope.
- H3-03 custody contracts, quarantine and verification, substitution and malware
  rejection, classification monotonicity, immutable version lineage, deterministic
  extraction replay, governed chunks, legal hold and retention precedence, durable
  deletion recovery, export and restore integrity, forced RLS, migration, guarded
  rollback, and architecture scope.
- H3-04 typed claim identity, changed-input replay denial, source-span custody,
  confidence and validity, classification monotonicity, contradiction, review,
  deterministic timeline ordering/rebuild/checkpoints, audit separation, durable
  source disposition, forced RLS, migration, guarded rollback, and architecture scope.
- H3-05 governed-memory provenance, deterministic identity and consolidation,
  classification and model-egress controls, feedback, confirmation, expiry, pinning,
  supersession, transitive source invalidation, export, forced RLS, migration,
  guarded rollback, and architecture scope.
- PDF and DOCX extraction helpers.
- H0 architecture fitness, threat, isolation, authorization, encryption, custody,
  provider-conflict, lineage, AI security, entity integrity, and replay evidence.
- H1-01 model registration, composite tenant keys, PostgreSQL migration and rollback,
  deterministic ownership backfill, forced RLS, last-owner enforcement, transfer
  prohibition, and audit immutability.
- H1-02 canonical identity compatibility, duplicate-email safety, issuer/subject
  uniqueness, migration idempotency, atomic rollback, and forward-fix safeguards.
- H1-03 secret hashing, secure cookie and CSRF contracts, session rotation and
  revocation, invitation/recovery denial and replay rules, concurrent single use,
  atomic recovery, identity-link review, forced RLS, and guarded rollback.
- H1-04 membership modeling, fixed-role determinism, invitation acceptance,
  lifecycle transitions, repository scoping, composite-key attacks, forced RLS,
  migration backfill, rollback refusal, personal-workspace consistency, and
  concurrent last-owner preservation.
- H1-05 canonical roles and permissions, explicit allow/deny rules, deterministic
  decisions, unknown-permission denial, workspace mismatch denial, immediate
  revocation, forced-RLS permission joins, redacted audit/outbox evidence, migration
  rehearsal, and guarded rollback.
- H1-06 immutable execution contracts, request-scope reset, placement validation,
  transaction-local propagation, context-bound repositories, forced-RLS runtime
  roles, pool reset, deterministic replay, and schema-free rollback rehearsal.
- H1-07 managed-KMS contracts, authenticated encryption, key versioning, KEK and DEK
  rotation replay, legacy shadow verification, forced RLS, failure quarantine,
  emergency disable, additive migration, audit/outbox evidence, and guarded rollback.
- H1-08 deterministic envelopes, atomic audit/outbox/idempotency, optimistic
  concurrency, duplicate suppression, schema and poison quarantine, sequence-gap
  handling, authorized replay, forced RLS, tamper detection, migration rehearsal, and
  guarded rollback.
- H1-09 encrypted backup authentication, KMS failure, RPO/RTO enforcement, isolated
  restore equivalence, H1-only export manifests, explicit closure authorization,
  access revocation, legal-hold precedence, write freezing, eligible erasure, Phase 1
  provider preservation, receipt immutability, forced RLS, and guarded rollback.
- H1-10 synthetic two-tenant isolation, authorization, revocation, execution-context
  enforcement, messaging idempotency, encrypted restore, closure, deletion, and
  Formal H1 Exit architecture evidence.
- H2-01 connection lifecycle, registry validation, provider-account uniqueness,
  effective capabilities, execution-context enforcement, H1 authorization, composite
  placement integrity, forced RLS, cross-workspace denial, optimistic concurrency,
  atomic audit/outbox evidence, migration rehearsal, guarded rollback, and strict
  H2-02+ slice isolation.
- H2-02 credential context binding, redaction, semantic equivalence, inventory
  checksums, shadow replay, concurrent migration serialization, managed-key failures,
  rotation, emergency disable, forced RLS, migration rollback, and strict H2-03+
  slice isolation.
- H2-03 OAuth state/PKCE custody, binding, scope supersets, replay, expiry,
  cancellation, provider denial, concurrency, forced RLS, guarded rollback, and strict
  H2-04+ slice isolation.
- H2-04 mirror identity, authority decision tables, version/hash comparisons,
  tombstones, conflicts, canonical linkage, idempotent replay, stale outbound
  preconditions, cross-workspace attacks, forced RLS, guarded rollback, and strict
  H2-05+ slice isolation.
- H2-05 immutable DTO serialization, timezone/offset preservation, opaque pagination,
  version preconditions, capability discovery and negotiation, canonical errors and
  retry classification, mutation replay, shared second-provider conformance, SDK
  confinement, provider-branch rejection, and strict H2-06+ slice isolation.

Live integration verification has additionally covered:

- Gmail profile lookup, read/search operations, and email sending.
- Calendar listing and create/update/delete lifecycle.
- Drive list, search, upload, metadata read, binary download, PDF read, DOCX read,
  metadata/content update, deletion, and PostgreSQL synchronization before and after
  cleanup.

The test run currently emits one non-blocking Starlette/httpx deprecation warning.

## Known limitations

- `X-User-ID` remains trusted directly by Phase 1 routes; the H1-03 session lifecycle
  is intentionally not wired into production request authentication yet.
- H1 runtime paths remain intentionally unused by Phase 1 requests. Provider migration
  and Phase 1 cutover remain in later approved H2 slices.
- H2 connection and shadow credential records are intentionally not wired to Phase 1
  runtime reads, callbacks, APIs, or provider routes; H2-03 through H2-09 own the
  remaining staged migration and cutover.
- The shared Google callback remains under the Gmail URL for compatibility with the
  currently registered OAuth client. A neutral callback path would be clearer.
- The Drive integration uses the broad `drive` scope. Production deployments should
  evaluate whether narrower scopes can satisfy the product requirements.
- OAuth credentials use an environment-provided symmetric key without managed key
  rotation or a cloud KMS.
- OAuth state rows expire logically but are not removed by a scheduled cleanup job.
- Gmail read operations store message content in memory by design; there is no
  per-request opt-out or retention policy.
- Calendar currently operates on a supplied calendar ID (default `primary`) but does
  not expose a calendar-list endpoint.
- Drive metadata is synchronized opportunistically, not through Drive change
  notifications. External changes remain stale until the file is observed again.
- File upload and download buffering occurs in memory. There are no application-level
  size limits, resumable upload endpoints, streaming responses, or malware scanning.
- Google Docs are exported as plain text. PDF extraction has no OCR, and DOCX
  extraction focuses on paragraph text rather than full layout, tables, comments, or
  embedded media.
- Search covers Drive `name` and `fullText` only and does not expose the complete Drive
  query language.
- Provider API calls have no application-level retry/backoff, rate-limit strategy,
  audit log, metrics, or tracing.
- Tests are strong at the unit and live-smoke level but do not yet mock complete Google
  API failure modes or run automatically in CI.

## Recommended next steps

1. Add real authentication and derive the Wanderra user from a verified session
   instead of `X-User-ID`.
2. Introduce a neutral `/api/v1/google/oauth/callback`, register it in Google Cloud,
   and migrate all three integrations to a shared OAuth coordinator.
3. Add CI for linting, migrations, unit tests, and provider-contract tests; resolve the
   Starlette/httpx deprecation warning.
4. Add structured logs, audit records for external mutations, request IDs, metrics,
   tracing, retry/backoff, and quota-aware error handling.
5. Add streaming downloads, resumable uploads, explicit file-size limits, MIME/content
   validation, and malware scanning.
6. Add Drive change notifications or periodic reconciliation so PostgreSQL metadata
   reflects external edits and deletions.
7. Add a calendar-list endpoint, recurring-event controls, attendee notification
   options, and conflict/time-zone tests.
8. Add retention, redaction, and user-control policies for Gmail content stored in
   Atlas memory.
9. Move credential encryption to a managed KMS with key versioning and rotation, and
   add scheduled cleanup for expired OAuth states.
10. Expand document ingestion with OCR, table-aware DOCX parsing, richer Google Docs
    structure, chunking, and memory indexing for Atlas retrieval.
