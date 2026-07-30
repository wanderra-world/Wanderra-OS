# H2 Platform Migration Specification

Canonical implementation decomposition for Atlas Phase 2 Stage H2.

**Owner:** Atlas Core  
**Status:** Accepted; H2-01 and H2-02 accepted, H2-03 implementation under review
**Stage:** H2 — Phase 1 migration foundation  
**Architecture entry point:** [README_ARCHITECTURE.md](README_ARCHITECTURE.md)  
**Engineering gate:** [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#h2)  
**Predecessor evidence:** [H1_FORMAL_EXIT_REPORT.md](H1_FORMAL_EXIT_REPORT.md)

This document owns only the H2 slice sequence, slice objectives, boundaries,
dependencies, acceptance criteria, and evidence contract. It does not redefine domain
terms, architecture decisions, stage-level engineering rules, or later-stage scope.

Approval of this specification authorizes no production work by itself. Each slice
requires explicit user authorization after its predecessor is accepted and merged.

## 1. H2 vision

H2 moves the operationally proven Phase 1 Google Workspace integrations behind
provider-neutral Atlas connections and capability ports without interrupting existing
Gmail, Calendar, or Drive behavior.

At H2 exit:

- a workspace-scoped Atlas connection, not a Phase 1 user credential table, is the
  canonical integration boundary;
- managed envelope encryption protects connection credentials;
- OAuth transactions are replay-safe, incremental, and connection-aware;
- provider resources have stable mirror and external-reference identity;
- email, calendar, and storage application code depends on canonical contracts rather
  than Google SDK types;
- Google implements the same contracts required of future providers;
- shadow comparison proves canonical results match approved Phase 1 behavior before
  cutover;
- legacy paths remain recoverable until an explicit post-H2 removal gate.

H2 is a compatibility migration, not an integration expansion. Google remains the only
production provider exercised in H2.

## 2. Objectives

H2 MUST:

1. preserve every Formal H0 and Formal H1 security and tenancy invariant;
2. assign every connection and provider-owned record to exactly one workspace;
3. separate provider capability operations from synchronization state and conflict
   semantics;
4. reuse H1 identity, authorization, execution context, encryption, audit, outbox,
   idempotency, recovery, and closure infrastructure;
5. introduce additive schemas and reversible or guarded forward-fix migrations;
6. preserve existing Phase 1 APIs and live Google authorization;
7. prove provider-neutral behavior through shared contract tests and a mock second
   adapter;
8. migrate Gmail, Calendar, and Drive through shadow reads and evidence-based cutover;
9. leave durable synchronization execution, webhook processing, and job scheduling to
   H4;
10. produce a Formal H2 Exit decision before H3 begins.

## 3. Governing architecture

H2 implements, but does not modify:

- [ADR-002](DECISIONS.md#adr-002-build-a-modular-monolith-before-microservices):
  remain a modular monolith;
- [ADR-004](DECISIONS.md#adr-004-provider-apis-are-adapters-not-the-business-model):
  provider APIs are adapters;
- [ADR-007](DECISIONS.md#adr-007-use-current-state-persistence-plus-events-not-universal-event-sourcing):
  persist current state plus events;
- [ADR-020](DECISIONS.md#adr-020-evolve-through-expand-and-contract-migrations):
  use expand-and-contract migration;
- [ADR-022](DECISIONS.md#adr-022-use-cell-ready-composite-key-tenancy):
  use workspace-inclusive keys and forced RLS;
- [ADR-024](DECISIONS.md#adr-024-centralize-deterministic-authorization-at-application-boundaries):
  authorize before repository or provider access;
- [ADR-025](DECISIONS.md#adr-025-make-managed-per-record-envelope-encryption-a-prerequisite):
  protect provider credentials with managed envelope encryption;
- [ADR-026](DECISIONS.md#adr-026-separate-provider-capability-and-synchronization-contracts):
  separate capability and synchronization contracts;
- [ADR-029](DECISIONS.md#adr-029-require-audit-outbox-atomicity-and-explicit-event-semantics):
  commit material state, audit, and outbox evidence atomically;
- [ADR-032](DECISIONS.md#adr-032-make-request-actor-and-tenant-context-mandatory):
  require execution context.

The provider mirror authority and conflict contract remains owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#9-provider-mirror-authority-and-conflict-model).
The H2 stage gate remains owned by
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#h2).

## 4. Architecture principles

### 4.1 Workspace-first connections

A connection belongs to one workspace and one provider account boundary. Global user
identity may authorize creation, but never owns the connection or its provider data.
Cross-workspace sharing and transfer are prohibited in H2.

### 4.2 Provider-neutral application boundary

Application services consume versioned canonical request, response, error, capability,
and pagination contracts. Provider SDK clients, resources, exceptions, field names,
and raw payloads remain inside adapters.

### 4.3 Capability and synchronization separation

Capability ports execute user-requested provider operations. Synchronization contracts
represent mirrors, versions, authority, tombstones, conflicts, cursors, and
reconciliation state. Neither contract may absorb the responsibilities of the other.

### 4.4 Deny before provider access

Every capability call requires a valid execution context and deterministic
authorization decision. Missing workspace, actor, session, membership, permission,
connection capability, or credential availability fails closed before any network
call.

### 4.5 Managed secrets only

Raw authorization codes, access tokens, refresh tokens, PKCE verifiers, client secrets,
and decrypted credentials MUST NOT enter logs, audit payloads, events, exception text,
or durable test fixtures. Durable credentials use the accepted H1 envelope service.

### 4.6 Compatibility over premature removal

Legacy Phase 1 paths remain operational through additive backfill, shadow reads,
comparison, and explicit cutover flags. H2 does not remove legacy credential columns or
tables.

### 4.7 Evidence before cutover

No capability may switch from a Phase 1 path to its H2 adapter until canonical output,
error, pagination, authorization, and side-effect behavior pass the approved comparison
threshold and rollback rehearsal.

### 4.8 No durable processing before H4

H2 may define and persist synchronization contracts needed for migration evidence. It
MUST NOT add a scheduler, worker platform, webhook runtime, polling loop, lease system,
or background reconciliation engine.

## 5. Scope

H2 includes:

- workspace-scoped connection lifecycle;
- provider and provider-account identity;
- versioned capability grants and granted OAuth scopes;
- managed connection credential envelopes;
- replay-safe OAuth transactions with PKCE and incremental authorization;
- provider mirror, external reference, authority, version, tombstone, conflict, and
  comparison records;
- canonical email, calendar, and storage capability contracts;
- canonical provider error, pagination, version, and extension contracts;
- Google Gmail, Calendar, and Drive adapters;
- shared adapter conformance tests and mock second-provider adapters;
- Phase 1 backfill, shadow-read, comparison, cutover, and rollback tooling;
- H1-owned audit, outbox, idempotency, recovery, and closure integration;
- migration and compatibility evidence;
- Formal H2 Exit.

## 6. Non-goals

H2 MUST NOT implement:

- Microsoft 365, Exchange, IMAP, Dropbox, OneDrive, Slack, or another production
  provider;
- durable jobs, schedulers, synchronization workers, webhook ingress, polling, leases,
  dead letters, or job cancellation;
- continuous provider synchronization or conflict-resolution user interfaces;
- universal entities, contacts, companies, projects, tasks, or typed operational
  projections;
- document custody, extraction, knowledge, timeline, memory, embeddings, or search;
- agents, recommendations, workflows, or approvals;
- custom roles, ABAC, cross-workspace connections, workspace transfer, or cell
  migration;
- provider data deletion as part of H1 closure;
- removal of Phase 1 APIs, tables, credential fields, or compatibility code;
- broad provider SDK or public integration platform design.

## 7. Canonical H2 data boundaries

### 7.1 Connection aggregate

The connection aggregate is workspace-owned and contains:

- connection ID, workspace ID, organization ID, and placement cell ID;
- provider key and provider-account stable identifier;
- connection kind and lifecycle status;
- display metadata safe for application use;
- granted scopes and versioned capability grants;
- health state and last user-visible verification time;
- creator and last material actor references;
- optimistic version and lifecycle timestamps.

The connection aggregate contains no plaintext secret and no provider SDK object.
Provider keys are registry identifiers, not business-logic switches.

### 7.2 Connection credential envelope

Credential metadata references:

- workspace and connection;
- H1 encrypted-envelope record and encryption context version;
- credential kind and provider account;
- issued, refreshed, expired, revoked, and last-verified timestamps;
- granted scopes and credential generation;
- migration source and shadow-verification status.

The encrypted credential payload is opaque outside the provider credential adapter.

### 7.3 OAuth transaction

An OAuth transaction records:

- workspace, actor, intended connection, and provider;
- hashed state, hashed or encrypted PKCE verifier, redirect contract, requested
  capabilities, requested scopes, and incremental-authorization intent;
- creation, expiry, one-time completion, revocation, and failure metadata;
- correlation, authorization decision, and idempotency references.

State is single-use and bound to workspace, actor, provider, redirect target, and
transaction purpose. Returned scopes may be a valid superset; missing required or
unexpected disallowed scopes fail closed.

### 7.4 Provider mirror and external reference

H2 implements the accepted H0 mirror contract:

- unique identity:
  `(workspace_id, connection_id, resource_type, external_id)`;
- provider version/etag, provider timestamps, normalized hash, synchronization state,
  tombstone, authority policy, and conflict state;
- governed raw-payload reference only where custody has an approved owner;
- immutable external reference to a future canonical object where one exists.

H2 does not create universal entities. Canonical references may remain absent until H3.

### 7.5 Canonical capability contracts

Email, calendar, and storage contracts use:

- immutable canonical DTOs;
- explicit capability version;
- opaque cursor pagination;
- canonical timestamps with timezone/offset preservation;
- stable external IDs and version preconditions;
- idempotency keys for mutations;
- canonical error categories;
- optional provider extensions in a non-authoritative envelope.

Extensions cannot alter authorization, tenancy, audit, retention, or conflict policy.

## 8. Security requirements

Every H2 slice MUST prove applicable controls:

1. workspace-inclusive primary/candidate keys and composite foreign keys;
2. enabled and forced PostgreSQL RLS before runtime access;
3. execution-context enforcement at repositories and provider gateways;
4. deterministic authorization before secret decryption or network access;
5. managed envelope encryption with tenant-, connection-, provider-, credential-type-,
   and generation-bound authenticated data;
6. credential rotation, revocation, emergency disable, corrupted-ciphertext, wrong-key,
   and KMS-outage fail-closed behavior;
7. hashed, expiring, single-use OAuth state and PKCE replay protection;
8. redirect allowlisting and issuer/provider binding;
9. scope minimization, explicit capability mapping, and incremental-grant validation;
10. safe canonical errors without token, raw payload, PII, or provider diagnostic
    leakage;
11. atomic security-relevant state, audit, outbox, and idempotency evidence;
12. request correlation across application, adapter, audit, and provider-call evidence;
13. provider version preconditions and prohibition of destructive last-write-wins;
14. tombstones that do not silently erase governed Atlas evidence;
15. connection closure and credential inaccessibility integrated with H1 workspace
    closure evidence;
16. least-privilege runtime roles that cannot own tables, bypass RLS, administer KMS,
    or read unrelated credential envelopes.

No production fixture may contain reusable provider credentials. Live end-to-end
verification uses separately managed test authorization and redacted evidence.

## 9. H2 slice roadmap

| Slice | Name | Primary outcome |
|---|---|---|
| H2-01 | Connection registry and lifecycle foundation | Canonical workspace-scoped connections, provider registry, capability grants, lifecycle invariants, and RLS |
| H2-02 | Managed connection credentials and migration inventory | H1 envelope-backed credential records, Phase 1 inventory, shadow verification, and reauthorization fallback |
| H2-03 | OAuth transaction and incremental authorization boundary | Replay-safe canonical OAuth/PKCE transactions and callback dispatch independent of legacy table probing |
| H2-04 | Provider mirror and external-reference foundation | Stable external identity, authority, version, tombstone, conflict, and comparison persistence |
| H2-05 | Canonical capability contracts and provider SDK boundary | Versioned email/calendar/storage DTOs, errors, pagination, capabilities, extensions, and conformance kit |
| H2-06 | Gmail adapter and email shadow migration | Gmail behind the canonical email port with Phase 1-compatible comparison and rollback |
| H2-07 | Google Calendar adapter and calendar shadow migration | Calendar behind the canonical calendar port with Phase 1-compatible comparison and rollback |
| H2-08 | Google Drive adapter and storage shadow migration | Drive behind the canonical storage port with Phase 1-compatible comparison and rollback |
| H2-09 | Connection cutover and compatibility stabilization | Verified connection backfill, neutral routing, controlled cutover flags, rollback, and legacy-path ownership |
| H2-10 | Synthetic multi-provider conformance and Formal H2 Exit | Mock second-provider proof, integrated migration rehearsal, security review, and H2 acceptance |

The order is mandatory. A later slice cannot begin before its predecessor is accepted
and merged.

## 10. Slice specifications

### H2-01: Connection registry and lifecycle foundation

**Status:** Accepted and merged.

**Objective**

Introduce the canonical workspace-owned connection boundary without changing Phase 1
credential reads, OAuth callbacks, APIs, or provider behavior.

**Scope**

- Provider registry identifiers and provider family metadata.
- Canonical connection aggregate and lifecycle:
  `pending`, `active`, `degraded`, `reauthorization_required`, `revoked`, and `closed`.
- Versioned connection kinds and capability grants.
- Granted-scope metadata without copying secret material.
- Workspace, organization, cell, creator, optimistic version, and lifecycle evidence.
- Owner/admin creation and lifecycle authorization through the H1 boundary.
- Repository and service layers using H1 execution context.
- Atomic audit and outbox events.
- Additive migration, forced RLS, and Phase 1-safe rollback rehearsal.

**Boundaries**

- No credential payload or OAuth transaction.
- No provider mirror or external resource reference.
- No provider SDK call, adapter, capability port, backfill, or routing change.
- No Phase 1 table mutation.

**Dependencies**

- Formal H1 Exit;
- ADR-004, ADR-020, ADR-021, ADR-022, ADR-024, ADR-026, ADR-029, and ADR-032;
- accepted provider mirror and capability contracts in H0.

**Acceptance criteria**

- Every connection belongs to exactly one organization, workspace, and placement cell.
- Cross-workspace reads, writes, lifecycle changes, uniqueness probes, and joins fail
  in application and PostgreSQL tests.
- Provider account uniqueness is scoped by workspace, provider, connection kind, and
  stable provider-account identifier.
- Unknown providers, kinds, capabilities, statuses, and invalid transitions fail
  deterministically.
- Revoked or closed connections expose no effective capability.
- Material lifecycle changes atomically write audit and outbox evidence.
- Forced RLS applies to every tenant-owned H2-01 table.
- Upgrade, empty-database migration, populated Phase 1 migration, rollback, and
  repeated-upgrade rehearsal pass.
- All Phase 1 tests and runtime behavior remain unchanged.

**Required evidence**

- Connection model and lifecycle unit tests.
- PostgreSQL composite-key, RLS, concurrency, audit/outbox, migration, and rollback
  tests.
- Architecture fitness tests proving no provider SDK import or H2-02 concept.
- Complete regression, Docker, smoke, and required GitHub gate results.

**Acceptance evidence**

- [H2-01 implementation evidence](H2_01_ACCEPTANCE_EVIDENCE.md)
- [Connection lifecycle unit tests](tests/connections/test_h2_01_contracts.py)
- [PostgreSQL, RLS, migration, rollback, and concurrency tests](tests/connections/test_h2_01_postgres.py)
- [H2-01 slice-isolation architecture fitness tests](tests/architecture/test_h2_01_connection_scope.py)
- [Additive H2-01 migration](alembic/versions/0014_add_connection_foundation.py)

### H2-02: Managed connection credentials and migration inventory

**Status:** Implemented; pull-request acceptance pending.

**Objective**

Create the credential custody boundary and prove that existing Gmail, Calendar, and
Drive credentials can be migrated safely without changing active reads.

**Scope**

- Connection credential metadata referencing H1 encrypted envelopes.
- Provider-, connection-, credential-kind-, and generation-bound encryption context.
- Phase 1 credential inventory with row counts, checksums, scope inventory, and
  migration eligibility.
- Idempotent shadow encryption and equivalence verification.
- Credential generation, expiry, revocation, rotation, emergency disable, and
  reauthorization-required states.
- Reauthorization fallback without destroying a valid legacy credential.

**Boundaries**

- Legacy credential tables remain authoritative.
- No OAuth callback routing change.
- No provider capability call or adapter.
- No destructive legacy ciphertext removal.

**Dependencies**

- H2-01 and H1 managed envelope encryption.

**Acceptance criteria**

- Plaintext and raw token material never persists outside authenticated ciphertext.
- Cross-workspace, cross-connection, cross-provider, cross-kind, and cross-generation
  ciphertext substitution fails.
- Inventory and shadow migration are idempotent and resumable.
- Shadow-decrypted credentials match approved Phase 1 meaning before eligibility.
- KMS outage, corruption, revoked key, missing scope, and partial migration fail closed
  without invalidating the legacy path.
- Rotation and emergency disable produce audit/outbox evidence.
- Rollback or guarded forward-fix preserves working Phase 1 authorization.

**Required evidence**

- Credential encryption, rotation, substitution, redaction, and failure tests.
- Production-like migration inventory and checksum rehearsal.
- PostgreSQL RLS, rollback, and concurrent migration tests.
- No-secret architecture fitness scans.

**Acceptance evidence**

- [H2-02 implementation evidence](H2_02_ACCEPTANCE_EVIDENCE.md)
- [Credential contract unit tests](tests/connection_credentials/test_h2_02_contracts.py)
- [PostgreSQL, RLS, migration, rollback, and replay tests](tests/connection_credentials/test_h2_02_postgres.py)
- [H2-02 slice-isolation architecture fitness tests](tests/architecture/test_h2_02_credential_scope.py)
- [Additive H2-02 migration](alembic/versions/0015_add_connection_credentials.py)
- [Credential migration and recovery runbook](H2_02_CREDENTIAL_OPERATIONS.md)

### H2-03: OAuth transaction and incremental authorization boundary

**Objective**

Replace provider-table callback discovery with a canonical, workspace-bound,
single-use OAuth transaction while preserving current Google callback compatibility.

**Scope**

- Canonical OAuth transaction and lifecycle.
- PKCE, state, expiry, redirect allowlist, issuer/provider binding, scope request, and
  incremental authorization.
- Callback transaction lookup and deterministic provider-adapter dispatch contract.
- Superset-scope acceptance and required-scope enforcement.
- Credential generation handoff to H2-02.
- Replay, cancellation, denial, provider-error, and reauthorization paths.

**Boundaries**

- Google may be the first OAuth protocol adapter, but no Gmail/Calendar/Drive business
  operation moves behind neutral capability ports yet.
- Existing callback URL remains supported.
- No Microsoft or other production OAuth provider.

**Dependencies**

- H2-01 and H2-02.

**Acceptance criteria**

- State and PKCE material are never persisted or logged raw.
- Callback state is one-time, expiring, workspace-, actor-, redirect-, purpose-, and
  provider-bound.
- Replayed, expired, cancelled, mismatched, or already-completed callbacks fail closed.
- Valid combined Gmail, Calendar, and Drive scope supersets are accepted.
- Missing required or disallowed unexpected scope outcomes are deterministic.
- Callback dispatch no longer depends on probing legacy provider state tables.
- Existing registered callback and Phase 1 incremental authorization remain compatible.

**Required evidence**

- OAuth state, PKCE, replay, expiry, scope, redirect, issuer, concurrency, and redaction
  tests.
- PostgreSQL RLS and migration rehearsal.
- Existing Gmail, Calendar, and Drive OAuth regression tests.
- [H2-03 implementation evidence](H2_03_ACCEPTANCE_EVIDENCE.md)
- [H2-03 contract and PostgreSQL tests](tests/oauth_transactions/)
- [H2-03 slice-isolation fitness tests](tests/architecture/test_h2_03_oauth_scope.py)
- [Additive H2-03 migration](alembic/versions/0016_add_oauth_transactions.py)

### H2-04: Provider mirror and external-reference foundation

**Objective**

Implement stable provider-resource identity and synchronization state without adding
continuous synchronization execution.

**Scope**

- Provider mirror, external reference, authority policy, version/etag, normalized
  hash, tombstone, conflict, and comparison records.
- Canonicalization state with optional future canonical reference.
- Inbound comparison and outbound-precondition decision contracts.
- Explicit conflict creation and user-resolution evidence contract.
- H1 audit/outbox/idempotency integration.

**Boundaries**

- No universal entity or typed H3 aggregate.
- No raw payload blob custody without an existing approved storage owner.
- No webhook, polling, worker, scheduler, or automatic conflict resolution.
- No provider adapter invocation.

**Dependencies**

- H2-01 and the H0 provider mirror contract.

**Acceptance criteria**

- Mirror identity is uniquely scoped by workspace, connection, resource type, and
  external ID.
- Version comparisons are deterministic; stale outbound preconditions never blindly
  retry.
- Ambiguous authority enters conflict state rather than last-write-wins.
- Provider deletion produces a tombstone without erasing governed Atlas evidence.
- External references are immutable in provider identity fields.
- Cross-workspace collision, join, update, and conflict-resolution attacks fail.
- Replayed mirror observations and decisions are idempotent.

**Required evidence**

- Authority decision-table and conflict contract tests.
- PostgreSQL RLS, composite-key, concurrency, idempotency, tombstone, migration, and
  rollback tests.
- Architecture fitness evidence proving H3/H4 boundaries.

### H2-05: Canonical capability contracts and provider SDK boundary

**Objective**

Define versioned provider-neutral email, calendar, and storage contracts and a reusable
adapter conformance kit before moving production behavior.

**Scope**

- Canonical DTOs for required Phase 1 operations.
- Capability discovery and version negotiation.
- Stable provider error taxonomy and retry classification.
- Opaque pagination cursors, time semantics, version preconditions, idempotency, and
  extensions envelope.
- Email, calendar, and storage ports.
- Shared conformance suite and deterministic in-memory mock second provider.
- Static dependency rules forbidding provider SDK types outside adapters.

**Boundaries**

- Contracts cover only operations already required by Phase 1.
- No lowest-common-denominator provider-name branches.
- No production adapter routing or Phase 1 cutover.
- No synchronization execution.

**Dependencies**

- H2-01 through H2-04.

**Acceptance criteria**

- Canonical contracts represent all approved Phase 1 Gmail, Calendar, and Drive
  behavior without Google types.
- Optional behavior is capability-discovered and versioned.
- Errors distinguish authentication, authorization, scope, rate limit, transient,
  conflict, not found, invalid input, quota, and unsupported capability.
- Cursor and extension data are opaque and non-authoritative.
- A deterministic mock second provider passes the shared conformance suite.
- Architecture fitness rejects Google imports and provider-name branching in
  business/application modules.

**Required evidence**

- Contract unit and serialization tests.
- Shared conformance suite results for mock adapters.
- Static dependency and provider-leakage fitness tests.
- API compatibility mapping for every Phase 1 operation.

### H2-06: Gmail adapter and email shadow migration

**Objective**

Move Gmail behavior behind the canonical email port with shadow comparison and
reversible routing.

**Scope**

- Gmail adapter translating canonical email DTOs, commands, errors, cursors,
  capabilities, and extensions.
- Connection credential lookup through H2-02.
- Provider mirror observation for exercised email resources.
- Shadow reads and comparison for profile, list, search, metadata/content read, and
  approved message projection.
- Approval-gated send path with idempotency and post-write verification.
- Per-workspace routing flag and rollback.

**Boundaries**

- No continuous mail synchronization, webhook, history cursor worker, timeline,
  memory ingestion, or second production provider.
- Phase 1 API contracts remain stable.

**Dependencies**

- H2-01 through H2-05.

**Acceptance criteria**

- Existing Gmail tests pass through the neutral port.
- Shadow results match canonical Phase 1 outputs for approved fixtures and live test
  authorization.
- Send retains approval, authorization, idempotency, audit, and verification controls.
- Google SDK objects and exceptions do not escape the adapter.
- Disabling the routing flag restores the legacy path without credential loss.
- Cross-workspace connection or credential use fails before the provider call.

**Required evidence**

- Shared email conformance results.
- Gmail adapter unit, integration, shadow comparison, mutation, error, rollback, and
  end-to-end tests.
- Provider SDK boundary fitness evidence.

### H2-07: Google Calendar adapter and calendar shadow migration

**Objective**

Move Calendar behavior behind the canonical calendar port with shadow comparison and
reversible routing.

**Scope**

- Calendar adapter for calendar listing and event read/create/update/delete behavior
  already present in Phase 1.
- Canonical timezone, recurrence pass-through, attendee, version, error, and capability
  translation.
- Connection credential and provider mirror integration.
- Shadow reads, mutation verification, routing flag, and rollback.

**Boundaries**

- No continuous synchronization, push notifications, scheduling agent, or new calendar
  product capability.

**Dependencies**

- H2-01 through H2-06.

**Acceptance criteria**

- Existing Calendar tests pass through the neutral port.
- Timezone and offset semantics round-trip without silent normalization loss.
- Update/delete uses version preconditions where available and never blind retries a
  conflict.
- Shadow outputs match approved Phase 1 behavior.
- Routing rollback restores the legacy path.
- Cross-workspace access fails before provider invocation.

**Required evidence**

- Shared calendar conformance results.
- Google Calendar unit, integration, conflict, shadow, rollback, and end-to-end tests.
- Provider SDK boundary fitness evidence.

### H2-08: Google Drive adapter and storage shadow migration

**Objective**

Move Drive behavior behind the canonical storage port with shadow comparison and
reversible routing.

**Scope**

- Drive adapter for list, search, metadata, download, upload, update, delete, Google
  Docs read, PDF read, and DOCX read behavior already present in Phase 1.
- Canonical file identity, MIME type, checksum/version, pagination, error, capability,
  and extension translation.
- Connection credential and provider mirror integration.
- Shadow reads, mutation verification, routing flag, and rollback.

**Boundaries**

- No H5 document custody, malware pipeline, extraction framework, continuous change
  feed, resumable upload product API, or new storage provider.

**Dependencies**

- H2-01 through H2-07.

**Acceptance criteria**

- Existing Drive tests pass through the neutral port.
- Binary content is not duplicated into PostgreSQL.
- Metadata identity and version preconditions are preserved.
- Shadow outputs match approved Phase 1 behavior for every supported MIME path.
- Upload/update/delete remain authorization-, approval-, idempotency-, audit-, and
  verification-controlled.
- Routing rollback restores the legacy path.
- Cross-workspace access fails before provider invocation.

**Required evidence**

- Shared storage conformance results.
- Drive unit, integration, content, shadow, mutation, rollback, metadata synchronization,
  and end-to-end tests.
- Provider SDK and document-custody boundary fitness evidence.

### H2-09: Connection cutover and compatibility stabilization

**Objective**

Complete verified connection backfill and make neutral connection routing the default
without deleting the Phase 1 fallback.

**Scope**

- Idempotent default workspace-to-connection backfill for existing integrations.
- Credential migration eligibility and connection binding.
- Per-capability shadow metrics and comparison thresholds.
- Controlled read and mutation cutover flags.
- Rollback playbook, failure budget, reauthorization fallback, and compatibility-code
  owner/removal milestone.
- Updated H1 recovery/export/closure manifests for H2-owned records.

**Boundaries**

- No legacy table or credential-column removal.
- No provider deletion during closure.
- No permanent worker, webhook runtime, or H3 concept.

**Dependencies**

- H2-01 through H2-08.

**Acceptance criteria**

- Backfill is deterministic, idempotent, restartable, and produces row-count/checksum
  evidence.
- Every valid Phase 1 integration maps to exactly one expected workspace connection or
  an explicit reauthorization exception.
- Neutral routing is default only after shadow thresholds pass.
- A tested flag rollback restores Phase 1 routing without data or credential loss.
- Recovery, restore, export, retention, and closure include H2-owned state while
  preserving provider-reconciliation boundaries.
- Compatibility code has a named owner and H7 removal gate.

**Required evidence**

- Production-like backfill rehearsal and reconciliation report.
- Cutover/rollback fault-injection tests.
- Recovery, closure, export, RLS, migration, and full Phase 1 regression results.
- Operational runbook and compatibility inventory.

### H2-10: Synthetic multi-provider conformance and Formal H2 Exit

**Objective**

Prove the H2 migration foundation is provider-neutral, secure, reversible, and ready
for H3.

**Scope**

- Two synthetic workspaces and independent connections.
- Google adapters plus deterministic mock second-provider adapters through shared
  capability contracts.
- Authorized and adversarial capability calls.
- Credential revocation, OAuth replay, provider conflict, idempotency, version
  precondition, shadow mismatch, cutover, rollback, backup, restore, closure, and
  deletion rehearsal.
- Complete H0/H1/H2 regression, architecture, migration, Docker, and security suites.
- H2 evidence matrix and formal security review.

**Boundaries**

- Evidence and defect remediation only.
- No H3 universal entity, H4 worker, H5 document, H6 search/memory, or H8 agent work.
- Architecture-changing remediation requires a superseding ADR.

**Dependencies**

- H2-01 through H2-09 accepted and merged.

**Acceptance criteria**

- Gmail, Calendar, and Drive pass approved end-to-end behavior through neutral ports.
- Mock second providers pass the same required conformance suites.
- Shadow reads match approved canonical outputs and cutover rollback succeeds.
- No provider SDK or payload dependency remains in business/application modules.
- Cross-workspace connection, credential, mirror, OAuth, export, and capability attacks
  fail.
- No unresolved critical or high security finding lacks explicit, time-bounded risk
  acceptance.
- All H2 prerequisites, deliverables, tests, and exit criteria in
  `IMPLEMENTATION_GUIDE.md` are accepted with evidence.
- The merge-blocking CI gate is green and Formal H2 Exit is explicitly accepted before
  H3 begins.

**Required evidence**

- Integrated synthetic multi-provider vertical-slice tests.
- Complete H2 evidence matrix and security review.
- Migration, cutover, rollback, recovery, closure, Docker, and CI records.
- Formal H2 Exit Report.

## 11. Dependency graph

```text
Formal H1 Exit
  |
  v
H2-01 Connections
  |
  v
H2-02 Credentials/inventory
  |
  v
H2-03 OAuth transactions
  |
  v
H2-04 Mirrors/external references
  |
  v
H2-05 Neutral contracts/conformance
  |
  v
H2-06 Gmail adapter
  |
  v
H2-07 Calendar adapter
  |
  v
H2-08 Drive adapter
  |
  v
H2-09 Cutover/stabilization
  |
  v
H2-10 Formal H2 Exit
```

The linear order is intentional. It prevents credential custody from depending on a
provider adapter, prevents adapters from inventing incompatible contracts, and
prevents cutover before all three Phase 1 capabilities have reversible neutral paths.

## 12. Testing strategy

### 12.1 Test layers

Each slice adds applicable:

- pure unit tests for lifecycle, mapping, normalization, authority, errors, and
  decision contracts;
- repository/service integration tests;
- real PostgreSQL migration, forced-RLS, composite-key, concurrency, idempotency, and
  rollback tests;
- shared provider conformance tests;
- Phase 1 regression tests;
- architecture fitness tests;
- Docker build and smoke verification;
- live Google end-to-end verification only where provider behavior changes.

### 12.2 Mandatory negative paths

Tests MUST cover missing context, cross-workspace access, revoked membership, revoked
connection, disabled credential, scope mismatch, OAuth replay, expired state,
credential substitution, KMS failure, provider transient failure, rate limit, stale
version, conflict, duplicate request, partial migration, shadow mismatch, rollback,
and redaction.

### 12.3 Contract compatibility

Canonical DTO and event schemas are versioned. Golden fixtures may verify
serialization, but provider payload fixtures stay in adapter tests. Contract changes
require compatibility tests for every accepted adapter.

### 12.4 End-to-end evidence

Live tests use a dedicated test workspace/connection and reversible temporary
resources. Evidence records identifiers, outcomes, and timings but never credentials
or sensitive content.

## 13. Migration policy

H2 follows [ADR-020](DECISIONS.md#adr-020-evolve-through-expand-and-contract-migrations)
and the migration rules in
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#6-migration-rules).

Every schema slice MUST:

1. expand additively;
2. support empty and populated Phase 1 databases;
3. inventory affected rows before mutation;
4. use deterministic, idempotent, resumable backfill;
5. preserve existing IDs and foreign keys;
6. record counts, checksums, exceptions, and completion evidence;
7. prove downgrade before H2 state exists or enforce a reviewed forward-fix after it
   exists;
8. keep legacy reads authoritative until the relevant cutover gate;
9. avoid destructive contraction in H2.

Credential migration is an online shadow migration. A legacy credential remains
available until its managed-envelope equivalent is verified, routing is cut over, and
rollback has been rehearsed. Reauthorization exceptions are explicit and must not
invalidate unrelated provider grants.

## 14. Rollback and forward-fix strategy

Each slice MUST document:

- the last safe schema revision;
- whether downgrade is safe for empty, shadow-only, and cutover states;
- data/state that would make downgrade lossy;
- the guarded forward-fix procedure;
- feature flags and routing switches;
- credential and OAuth recovery;
- audit/outbox reconciliation;
- provider-side effect reconciliation;
- owner, decision authority, and maximum rollback window.

Application rollback and schema rollback are separate decisions. Provider mutations
cannot be undone by database rollback; they require idempotent retry, verification, or
capability-specific compensation.

H2-06 through H2-09 MUST prove that disabling the neutral route restores the Phase 1
path without changing valid provider credentials or duplicating provider effects.

## 15. CI requirements

Every H2 pull request MUST pass the existing protected `H0 Required Gate`, which
continues to run:

- Architecture Fitness;
- complete regression tests with PostgreSQL and RLS;
- Docker build and smoke verification;
- the aggregate required gate.

H2 adds no weaker parallel gate. H2 evidence becomes part of the existing mandatory
suites. CI MUST fail on:

- provider SDK imports outside adapters;
- provider-name branching in business/application modules;
- context-free H2 repositories or provider gateways;
- tenant tables without forced RLS;
- secret-like fields in logs, audit, events, fixtures, or exception payloads;
- missing migration rehearsal;
- missing shared conformance tests for an accepted adapter;
- Phase 1 regression failure;
- H2-02 or later concepts appearing in H2-01, or equivalent later-slice leakage.

Branch protection, required checks, up-to-date branches, conversation resolution,
linear history, and no-bypass settings remain H1 production invariants.

## 16. Documentation requirements

Each slice MUST update only applicable:

- `PROJECT_STATUS.md` with verified current-state claims;
- its acceptance-evidence links in this specification;
- operational runbooks for OAuth, credential recovery, migration, cutover, and
  rollback;
- compatibility inventory and removal owner;
- API or provider contract documentation where behavior is introduced;
- `README_ARCHITECTURE.md` only for navigation or stage status.

Architecture, ADRs, and roadmap are not changed by implementation. A fundamental
conflict stops implementation and requires architecture review and a superseding ADR.

Documentation MUST distinguish:

- implemented from proposed;
- legacy-authoritative from shadow and cutover;
- provider mirror from canonical operational truth;
- capability execution from synchronization state;
- local automated evidence from live provider evidence.

## 17. Evidence requirements

Every slice produces a committed evidence section containing:

- governing scope and explicit exclusions;
- migration revision or explicit schema-free rationale;
- unit, PostgreSQL, RLS, integration, architecture, regression, and Docker results;
- migration upgrade/downgrade or forward-fix rehearsal;
- rollback result;
- production behavior and schema impact;
- security negative-path results;
- compatibility and provider conformance results;
- open findings with severity, owner, and expiry;
- confirmation that no later H2 slice was introduced;
- pull request and required-gate result after GitHub completion.

Evidence MUST be reproducible from committed tests and scripts. Narrative claims alone
do not satisfy an acceptance criterion.

## 18. Definition of Ready

An H2 slice may begin only when:

- its predecessor is accepted and merged;
- the user explicitly authorizes that slice;
- its objective, scope, boundaries, dependencies, acceptance criteria, and evidence are
  present in this accepted specification;
- all referenced ADRs and H0/H1 contracts are accepted;
- security, migration, compatibility, and rollback impact are reviewed;
- required provider test authorization is available or the slice is explicitly
  non-live;
- no unresolved architecture conflict exists.

## 19. Definition of Done

Every H2 slice is done only when:

1. implementation remains inside the approved slice;
2. typed production code, repositories, services, migrations, and tests are complete
   where required;
3. no provider-specific business/application logic or duplicate canonical model is
   introduced;
4. authorization, execution context, forced RLS, encryption, audit, outbox,
   idempotency, recovery, and closure integration pass where applicable;
5. Phase 1 APIs and behavior remain backward compatible;
6. migration and rollback or guarded forward-fix rehearsal pass;
7. required unit, PostgreSQL, integration, contract, architecture, regression, Docker,
   smoke, and live tests pass;
8. documentation and acceptance evidence are current;
9. no unresolved TODO, critical finding, or high finding remains without explicit,
   time-bounded acceptance;
10. the dedicated pull request is limited to one slice and all mandatory GitHub checks
    pass;
11. the slice is explicitly accepted and merged;
12. no later H2 slice has started.

The general engineering Definition of Done in
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#5-definition-of-done) also applies.

## 20. Formal H2 Exit

H2 closes only through H2-10 after:

- H2-01 through H2-09 are accepted and merged;
- every stage prerequisite, deliverable, required test, and exit criterion is traced to
  passing evidence;
- Gmail, Calendar, and Drive operate through neutral ports with verified rollback;
- the mock second provider proves the contracts are not Google-shaped;
- migration, recovery, closure, and security reviews are complete;
- no unaccepted critical or high finding remains;
- the merge-blocking gate is green;
- a Formal H2 Exit Report is reviewed and accepted.

Formal H2 Exit authorizes consideration of H3. It does not automatically authorize H3
implementation.
