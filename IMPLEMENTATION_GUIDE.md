# Atlas Implementation Guide

Permanent engineering contract for implementing the approved Atlas architecture.

**Owner:** Atlas Engineering  
**Status:** Normative  
**Applies to:** Every Atlas engineer, pull request, migration, integration, worker,
administrative operation, and agent capability
**Architecture entry point:** [README_ARCHITECTURE.md](README_ARCHITECTURE.md)  
**Implementation sequence owner:**
[ARCHITECTURE_HARDENING.md](ARCHITECTURE_HARDENING.md#revised-phase-2-implementation-sequence)

This is not an architecture document. It does not introduce new domain concepts or
replace an Architecture Decision Record (ADR). It translates approved architecture
into implementation rules and release gates.

When this guide and an architecture document appear to conflict, implementation stops.
The architecture is reviewed and, when the decision is fundamental, a superseding ADR
is approved before code changes.

## 1. Contract language and precedence

The words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**, and **MAY**
express obligation levels.

Implementation is governed in this order:

1. security, tenancy, privacy, and legal invariants;
2. accepted superseding ADRs in [DECISIONS.md](DECISIONS.md);
3. the document hierarchy in
   [README_ARCHITECTURE.md](README_ARCHITECTURE.md#architecture-document-hierarchy);
4. this engineering contract;
5. local module conventions that do not conflict with the above.

This guide owns engineering workflow, readiness, completion, testing, migration, and
pull-request requirements. Architecture documents own system structure and decisions.

## 2. Engineering principles

### 2.1 Architecture before code

- Every change MUST be traceable to an approved architecture section.
- A fundamental decision MUST have an accepted ADR before implementation.
- Engineers MUST search the Architecture Index and referenced documents before
  introducing a model, term, boundary, port, event, permission, or workflow.
- Existing concepts MUST be extended instead of recreated under another name.
- Architectural drift or conflict MUST be reported and resolved before coding.

### 2.2 Security before features

- Workspace isolation, authorization, data classification, secret handling, audit,
  retention, and deletion are feature requirements, not later hardening work.
- Access is deny-by-default and MUST be checked in the application layer before
  repository or provider access.
- Defense-in-depth controls, including composite tenant keys and PostgreSQL RLS, MUST
  not be bypassed for convenience.
- No feature may ship with a known critical threat unless the risk has formal,
  time-bounded acceptance by the accountable owner.

Relevant decisions:
[ADR-021](DECISIONS.md#adr-021-require-organization-ownership-for-every-workspace),
[ADR-022](DECISIONS.md#adr-022-use-cell-ready-composite-key-tenancy),
[ADR-024](DECISIONS.md#adr-024-centralize-deterministic-authorization-at-application-boundaries),
and
[ADR-025](DECISIONS.md#adr-025-make-managed-per-record-envelope-encryption-a-prerequisite).

### 2.3 Tests before merge

- Required tests MUST be committed with or before implementation.
- A failing required test blocks merge.
- A defect fix MUST include a regression test.
- Architectural invariants MUST be covered by architecture fitness tests where they
  can be automated.
- Tests MUST prove negative paths, including unauthorized, cross-workspace, duplicate,
  stale, partial-failure, and retry behavior.

### 2.4 Backward-compatible migrations

- Atlas MUST evolve through expand-and-contract migrations.
- Phase 1 Gmail, Calendar, and Drive behavior MUST remain operational throughout the
  migration.
- Destructive contraction occurs only after backfill, compatibility operation,
  verification, rollback or forward-fix rehearsal, and an explicit removal gate.

Relevant decision:
[ADR-020](DECISIONS.md#adr-020-evolve-through-expand-and-contract-migrations).

### 2.5 Provider-neutral design

- Business and application modules MUST depend on Atlas capability ports and canonical
  DTOs, never provider SDK types or payloads.
- Provider-specific behavior belongs in adapters or explicit extension envelopes.
- Capability support MUST be discovered through contracts, not provider-name branches.
- Every adapter MUST pass shared contract tests.

Relevant decisions:
[ADR-004](DECISIONS.md#adr-004-provider-apis-are-adapters-not-the-business-model) and
[ADR-026](DECISIONS.md#adr-026-separate-provider-capability-and-synchronization-contracts).

### 2.6 Simplicity over cleverness

- Prefer explicit typed models, commands, policies, and transaction boundaries.
- Do not introduce EAV business models, generalized knowledge graphs, universal event
  sourcing, microservices, or infrastructure without an approved measured need.
- Optimize first for correctness, explainability, operability, and removal.
- Abstractions MUST have at least one concrete need and a clear owner.

Relevant decisions:
[ADR-002](DECISIONS.md#adr-002-build-a-modular-monolith-before-microservices),
[ADR-028](DECISIONS.md#adr-028-constrain-universal-entities-and-the-phase-2-core), and
[ADR-007](DECISIONS.md#adr-007-use-current-state-persistence-plus-events-not-universal-event-sourcing).

## 3. Canonical implementation order

H0 through H2 retain the approved hardening sequence. ADR-033 consolidates the former
H3–H8 packaging into the final H3 program. Future renaming or reordering requires an
Architecture Index update and a superseding ADR.

The requested engineering areas map to the canonical stages as follows:

| Engineering area | Canonical stage |
|---|---|
| Foundation | H0 and H1 |
| Identity | H1 |
| Workspaces | H1 |
| Permissions | H1; H3 resource grants reuse H1 authorization |
| Connections | H2; H3 durable work consumes H2 ports |
| Universal Resources | H3-01 |
| Documents, Knowledge, and Memory | H3-03 through H3-05 |
| Search | H3-06 |
| Tasks, Workflows, and Notifications | H3-07 through H3-09 |
| Agent platform contracts | H3-10; business agents remain post-H3 |

Stages are sequential release gates. Limited exploratory prototypes MAY run earlier
only when H0 explicitly requires them; they are not production implementation.

### H0

**Architecture purpose:**
[Stage H0](ARCHITECTURE_HARDENING.md#stage-h0-architecture-hardening)

**Prerequisites**

- Phase 1 baseline and end-to-end tests are reproducible.
- `README_ARCHITECTURE.md`, `ARCHITECTURE_REVIEW.md`, and
  `ARCHITECTURE_HARDENING.md` are reviewed.
- Owners and approvers are assigned for every P0 deliverable.

**Deliverables**

- All P0.1–P0.14 issues are resolved or formally rejected with rationale.
- Required ADRs are superseded or amended through new ADR records.
- Approved tenancy, IAM, authorization, encryption, provider conflict, object custody,
  deletion, event/job, AI egress, and canonical-schema specifications exist.
- Executable prototypes validate database isolation, authorization, encryption,
  provider conflict, and event semantics.
- Architecture fitness-test harness exists.
- SLO, RPO, and RTO targets are approved.

**Required tests**

- Prototype cross-workspace isolation and privilege-escalation tests.
- Composite tenant-key and RLS failure tests.
- Authorization decision-table tests.
- Encryption rotation and credential-revocation tests.
- Event duplication, ordering, replay, and poison-message tests.
- Architecture dependency and provider-leakage fitness tests.

**Exit criteria**

- The P0 Architecture Gate in `README_ARCHITECTURE.md` is signed off.
- No unresolved critical threat exists without explicit risk acceptance.
- Production Phase 2 schemas and feature code have not preceded the gate.

### H1

**Architecture purpose:**
[Stage H1](ARCHITECTURE_HARDENING.md#stage-h1-platform-skeleton)

**Slice decomposition:**
[H1 Platform Skeleton Specification](H1_PLATFORM_SPEC.md)

**Prerequisites**

- H0 exit criteria are met.
- Identity lifecycle, workspace ownership, authorization, tenant database, encryption,
  audit, and event specifications are approved.
- Migration and rollback or forward-fix plans exist for affected Phase 1 data.

**Deliverables**

- Organizations and workspaces.
- Canonical identities, sessions, memberships, fixed roles, and policy decisions.
- Request and actor context propagated through commands, repositories, events, and
  jobs.
- Composite tenant keys, RLS, and workspace placement metadata.
- KMS-backed envelope encryption.
- Immutable audit path and transactional outbox/inbox.
- Architecture fitness tests in continuous integration.

**Required tests**

- Unit tests for identity lifecycle, membership, fixed-role permissions, and policies.
- Integration tests for session revocation and authorization enforcement.
- Adversarial cross-workspace read, write, uniqueness, join, export, and job tests.
- Atomic state/audit/outbox transaction tests.
- Event idempotency, backup, restore, and deletion tests.
- Migration upgrade and downgrade or proven forward-fix tests.

**Exit criteria**

- A synthetic tenant vertical slice proves isolation, revocation, audit, event
  idempotency, backup, and deletion.
- No repository accepts tenant-owned access without explicit workspace context.
- Security review has no unaccepted critical or high finding.

### H2

**Architecture purpose:**
[Stage H2](ARCHITECTURE_HARDENING.md#stage-h2-phase-1-migration-foundation)

**Prerequisites**

- H1 exit criteria are met.
- Provider mirror, field authority, conflict, OAuth, credential, and synchronization
  contracts are approved.
- Default organization/workspace backfill and credential re-encryption plans exist.

**Deliverables**

- Unified connections, credentials, OAuth transactions, provider mirrors, and external
  references.
- Provider-neutral email, calendar, and storage ports with canonical DTOs.
- Google adapters behind those ports.
- Backfill, shadow-read, comparison, and cutover tooling.
- Capability discovery and explicit provider extension handling.

**Required tests**

- Shared provider contract tests.
- OAuth PKCE, incremental-scope, state, expiry, replay, and revocation tests.
- Credential encryption and rotation tests.
- Provider mirror identity, authority, version, and conflict tests.
- Existing Gmail, Calendar, and Drive unit, integration, and end-to-end suites through
  neutral ports.
- Static or fitness tests that reject Google types in business/application modules.

**Exit criteria**

- Gmail, Calendar, and Drive pass existing end-to-end tests through neutral ports.
- Shadow reads match approved canonical outputs.
- No direct Google SDK or payload dependency remains in business/application code.
- Phase 1 behavior remains backward compatible.

### H3 System Intelligence Layer

ADR-033 consolidates the former H3–H8 delivery packaging into the final reusable H3
platform program. The canonical H3 implementation order, prerequisites, deliverables,
tests, compatibility, migration, and exit gates are owned by
[H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md). The component and slice
architecture is owned by [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md), and Formal H3 Exit
is owned by [H3_EXIT_DEFINITION.md](H3_EXIT_DEFINITION.md).

The historical sections below preserve the pre-ADR-033 review record only. They have
no implementation-authorizing or normative effect.

### IP-01 Provider-Neutral Integration Layer Foundation

ADR-034 authorizes IP-01 as the first post-H3 implementation slice after this
governance milestone is accepted and merged. IP-01 extends, and does not replace, the
accepted H2 integration architecture.

**Prerequisites**

- Formal H3 Exit is Accepted through PR #46 at `93a01f4`.
- `0032_h3_platform_hardening` is the accepted migration baseline.
- H2 connection, credential, OAuth transaction, capability, routing, encryption,
  audit, execution-context, and RLS contracts remain canonical.
- The IP-01 implementation branch starts only after this governance pull request is
  accepted and merged.

**Deliverables**

- One provider-neutral application composition boundary over the existing canonical
  H2 integration contracts.
- Workspace, organization, actor, connection, capability, and correlation context is
  required before any integration operation can be dispatched.
- Verified gaps only are closed without duplicating H2 models or changing accepted
  provider behavior.
- Architecture evidence maps every IP-01 contract to its existing H2 owner.

**Excluded work**

- Provider adapters and external network calls.
- Gmail or any other OAuth implementation or endpoint.
- Calendar, Drive, messaging, social, CRM, UI, synchronization, webhook, worker,
  agent, workflow, or business behavior.
- Credential migration, cutover, or removal of Phase 1 compatibility paths.

**Required tests**

- Unit tests for deterministic provider-neutral composition and fail-closed context.
- PostgreSQL/RLS tests for cross-workspace isolation if persistence changes are
  strictly required.
- Architecture Fitness tests rejecting provider SDKs, provider payloads, duplicated
  canonical models, context-free dispatch, and future-slice leakage.
- Complete regression, migration/rollback, Ruff, Docker, and smoke verification.

**Exit criteria**

- A provider-neutral caller can resolve an authorized workspace-owned connection and
  capability through existing H2 contracts without invoking a provider.
- Missing, mismatched, revoked, disabled, or unauthorized context fails before any
  adapter boundary.
- No H0-H3 contract or Phase 1 behavior changes.
- No provider implementation or external effect exists.
- Acceptance evidence and protected required checks pass, and the dedicated IP-01
  pull request is accepted and merged.

**Rollback**

IP-01 must be additive and independently disableable. Any additive persistence must
support empty downgrade and guarded populated rollback under the existing migration
policy. Removing the composition boundary restores the accepted H2 behavior without
credential, provider-state, or audit loss.

### IP-02 Gmail OAuth Workspace Connection

ADR-034 authorizes IP-02 as the only next implementation slice after this governance
milestone is accepted and merged. Gmail is the first provider implementation over
IP-01, not a new integration architecture.

**Prerequisites**

- IP-01 is Accepted and merged through PR #48 at `4bee069` with all protected checks
  passing.
- `0032_h3_platform_hardening` remains the accepted migration baseline because IP-01
  added no migration.
- H2 connection, encrypted credential, replay-safe OAuth transaction, Gmail capability
  adapter/routing, authorization, audit, execution-context, and forced-RLS contracts
  remain canonical.

**Deliverables**

- Workspace-bound Gmail authorization initiation and callback through the canonical
  H2 OAuth transaction boundary and IP-01 Integration Layer.
- Exactly one workspace owner for every Gmail connection, with multiple connections
  and Google accounts supported independently per workspace.
- Google account identity and provider/account consistency associated with the
  canonical H2 connection rather than a global Gmail account.
- Access and refresh credential material stored only through the existing managed
  encrypted credential boundary; secrets never enter logs, audit payloads, events, or
  API responses.
- Minimum Gmail scopes mapped to existing email capability grants, with no Calendar,
  Drive, Contacts, or unrelated Google scope.
- Authorization, state, PKCE, issuer/account consistency, replay, expiry, revocation,
  audit, and safe failure behavior through accepted H2/IP-01 contracts.

**Excluded work**

- Google Calendar, Drive, Contacts, or any combined Google Workspace scope expansion.
- WhatsApp, Stripe, LinkedIn, Facebook, Instagram, TikTok, YouTube, X, CRM, social or
  other provider implementation.
- UI/product behavior, synchronization, webhooks, marketing automation, business
  workflows, agents, or autonomous actions.
- Parallel Gmail connection, credential, OAuth, permission, provider, routing, or
  audit infrastructure.

**Required tests**

- OAuth initiation/callback, state, PKCE, issuer, expiry, replay, account mismatch,
  scope minimization, revocation, and secret-redaction tests.
- Authorized, unauthorized, inactive, disabled, revoked, missing-credential, and
  provider/account mismatch tests through IP-01.
- Multi-workspace and multi-account PostgreSQL/RLS tests proving no cross-workspace
  connection, credential, OAuth transaction, capability, or audit access.
- Existing Phase 1 Gmail compatibility and H2 email capability/routing regression.
- Architecture Fitness rejecting provider leakage into IP-01/core and duplicate
  integration/OAuth models.
- Complete regression, Ruff, migration/rollback, Docker, application smoke,
  durable-worker smoke, and protected required checks.

**Exit criteria**

- A separately authorized workspace can initiate and complete a replay-safe Gmail
  OAuth connection using its own canonical connection, Google account, capability
  grants, and encrypted credentials.
- Independent workspaces and accounts cannot resolve, read, refresh, revoke, or use
  one another's Gmail authorization.
- Invalid state, replay, expiry, account/provider mismatch, scope gap, inactive
  connection, or unavailable credential fails before provider capability use.
- No secret appears in logs, audit, events, exceptions, fixtures, or responses.
- Phase 1 and accepted H0-H3/IP-01 behavior remains backward compatible.
- No excluded provider, UI, workflow, or business-agent functionality exists.
- IP-02 acceptance evidence and all protected checks pass.

**Rollback**

IP-02 must preserve the accepted H2 legacy/shadow/canonical routing and credential
recovery controls. Any strictly required migration must be additive, forced-RLS
protected, support empty downgrade, and fail closed with a reviewed forward fix or
export once protected authorization state exists. Disabling the IP-02 route restores
the accepted pre-IP-02 path without credential loss or provider-side duplication.

### IP-03 Operator-facing Gmail Connection Lifecycle

ADR-034 authorizes IP-03 as the only next implementation slice after the governance
milestone accepting IP-02 is reviewed and merged. IP-03 exposes the already accepted
IP-02 composition to an authorized operator; it does not create another OAuth or
integration architecture.

**Prerequisites**

- IP-02 is Accepted and merged through PR #50 at `92de174`, with all protected checks
  passing.
- `0032_h3_platform_hardening` remains the accepted migration baseline because IP-02
  added no migration.
- Canonical identity/session, execution context, workspace membership, authorization,
  connection, OAuth transaction, encrypted credential, audit, and forced-RLS
  boundaries remain mandatory.

**Deliverables**

- An authenticated and authorized operator boundary that initiates Gmail OAuth for
  one explicitly selected workspace-owned canonical connection.
- Callback completion through the accepted IP-02/H2 single-use state and PKCE flow;
  callback state, not an untrusted workspace parameter, selects the transaction.
- A workspace-scoped connection-state query returning only identifiers, lifecycle
  status, provider-account display identity, granted capability/scope metadata, and
  timestamps that are approved for operator disclosure.
- Deterministic error translation for unauthorized, cross-workspace, invalid,
  expired, replayed, revoked, disabled, mismatched, or unavailable authorization.
- Existing audit/outbox evidence for initiation, completion, failure, and state reads,
  without secret or provider-payload disclosure.

**Excluded work**

- New OAuth, connection, credential, provider, identity, session, tenant, permission,
  routing, audit, or encryption models.
- Calendar, Drive, Contacts, WhatsApp, Stripe, CRM, social networks, or any additional
  provider capability.
- UI/product work, synchronization, webhooks, workflows, business agents, or mailbox
  operations beyond existing accepted compatibility behavior.

**Required tests**

- Authenticated operator, membership, permission, workspace binding, and capability
  grant tests before OAuth initiation or state access.
- Callback state/PKCE/issuer/redirect/expiry/replay tests through the real application
  boundary, including provider/account mismatch and safe provider failures.
- PostgreSQL/RLS tests for multiple workspaces and Google accounts, proving no
  cross-workspace connection, transaction, credential, audit, or status access.
- Response, exception, logging, audit, and outbox redaction tests.
- Phase 1 Gmail and accepted IP-01/IP-02 regression, Architecture Fitness, Ruff,
  Docker, application smoke, durable-worker smoke, and protected required checks.

**Exit criteria**

- An authorized operator can initiate and complete Gmail OAuth for one selected
  workspace connection and verify its non-secret resulting state.
- An operator in another workspace cannot discover, initiate, complete, or inspect
  that connection or its authorization.
- No token, client secret, authorization code, state secret, PKCE verifier,
  ciphertext, decrypted credential, or raw provider payload is returned or logged.
- No excluded provider, UI, workflow, mailbox expansion, or business-agent behavior
  exists; all existing contracts remain backward compatible.
- IP-03 acceptance evidence and all protected checks pass.

**Rollback**

IP-03 adds no persistence unless a separately reviewed existing-contract gap proves
it unavoidable. Disabling or reverting its operator boundary restores accepted IP-02
behavior without deleting connections, credentials, transactions, audit evidence, or
provider state. Any required schema change must return to governance before code.

### Gmail operational readiness / operator authentication and lifecycle plumbing

ADR-034 authorizes this as the only next slice after the governance milestone that
accepts IP-03 is reviewed and merged. The slice may close only the operational gaps
required for one safe human-operated Gmail authorization by composing accepted
identity/session, execution-context, membership, authorization, CSRF, managed KMS,
connection/credential lifecycle, audit, and forced-RLS boundaries.

The implementation MUST NOT create an authentication authority, allow unauthenticated
session issuance, expose `IdentityLifecycleService.issue_session()` as a login bypass,
change the accepted authentication model, modify IP-02/IP-03 OAuth contracts, or add
IP-04, another provider, UI, workflow, mailbox expansion, or business-agent behavior.
If no accepted authority can authenticate the initial operator, implementation must
stop and return to architecture governance before adding runtime code.

The accepted production migration baseline remains `0032_h3_platform_hardening`.
Any claimed schema requirement must return to governance before implementation.

### Historical H3: Minimum universal core (superseded by ADR-033)

**Architecture purpose:**
[Stage H3](ARCHITECTURE_HARDENING.md#stage-h3-minimum-universal-core)

**Prerequisites**

- H2 exit criteria are met.
- Minimum canonical core and entity/projection integrity rules are approved.
- Aggregate, transaction, ownership, permission, and deletion boundaries are defined.

**Deliverables**

- Entity registry with typed projection integrity.
- Typed contacts, companies, projects, and tasks.
- Relationships, tags, attachments, ownership, and resource grants.
- Immutable document versions in approved object storage.
- First complete provider-neutral domain vertical slice.

**Required tests**

- Entity/projection creation, consistency, versioning, and deletion tests.
- Typed domain invariant and optimistic-concurrency tests.
- Relationship endpoint, cardinality, and workspace-integrity tests.
- Permission and resource-grant tests.
- Object custody, content hash, immutable version, and attachment tests.
- Cross-workspace foreign-key and RLS adversarial tests.

**Exit criteria**

- A contact → company → project → task → email/file slice works end to end.
- Tenant integrity is enforced by both application policy and database constraints.
- No operational aggregate is stored as a generic EAV/JSON entity.

### Historical H4: Durable processing (superseded by ADR-033)

**Architecture purpose:**
[Stage H4](ARCHITECTURE_HARDENING.md#stage-h4-durable-processing-and-provider-synchronization)

**Prerequisites**

- H3 exit criteria are met.
- Event, job, idempotency, concurrency, webhook, reconciliation, and conflict
  specifications are approved.
- SLOs and provider quota policies are defined.

**Deliverables**

- Durable jobs with leases, retries, cancellation, dead letters, and replay.
- Authenticated webhooks, cursors, reconciliation, and conflict handling.
- Provider rate limiting, outage behavior, connection health, and operator controls.
- Correlated logs, metrics, traces, alerts, and operational dashboards.

**Required tests**

- Duplicate, reordered, delayed, and forged webhook tests.
- Worker crash, lease expiry, retry exhaustion, cancellation, and replay tests.
- Provider conflict and reconciliation tests.
- Expired credentials, rate-limit, quota, timeout, and outage tests.
- Load and soak tests against approved SLO thresholds.

**Exit criteria**

- Tested recovery exists for duplicate/reordered events, provider conflicts, expired
  credentials, quota limits, and worker crashes.
- Operators can detect, diagnose, pause, replay, and reconcile failed work.

### Historical H5: Documents and derivation (superseded by ADR-033)

**Architecture purpose:**
[Stage H5](ARCHITECTURE_HARDENING.md#stage-h5-documents-activity-and-governed-derivation)

**Prerequisites**

- H4 exit criteria are met.
- Document custody, classification, provenance, retention, extraction, and deletion
  lineage are approved.
- Timeline and audit contracts remain separate.

**Deliverables**

- Immutable document versions and content extraction.
- Versioned chunks and provenance-backed extracted attributes.
- Timeline projection, AI notes, classification, and retention enforcement.
- End-to-end derivative inventory and deletion lineage.
- No generalized knowledge graph.

**Required tests**

- Content hash, version lineage, extraction, and provenance tests.
- Classification and policy-enforcement tests.
- Timeline projection replay tests independent of immutable audit.
- Retention, legal-hold, expiry, and deletion verification tests.
- Source deletion propagation across object storage, database, indexes, embeddings, and
  caches.

**Exit criteria**

- Every derivative is traceable to its source, model or extractor version, and policy.
- Deletion is demonstrably complete or produces an explicit, auditable exception.

### Historical H6: Search and memory (superseded by ADR-033)

**Architecture purpose:**
[Stage H6](ARCHITECTURE_HARDENING.md#stage-h6-permission-aware-search-and-memory)

**Prerequisites**

- H5 exit criteria are met.
- Search ACL, embedding, model routing, AI egress, memory governance, expiry, and
  evaluation specifications are approved.
- pgvector migration and rollback or forward-fix plan exists.

**Deliverables**

- Full-text and pgvector search with structured filters and hybrid ranking.
- Search ACL projections and permission-aware retrieval.
- Versioned models, embeddings, and chunking.
- Governed memory with provenance, confidence, feedback, expiry, and deletion.
- Quality, safety, isolation, and latency evaluation harness.

**Required tests**

- Exact-match, hybrid-ranking, freshness, authority, and relevance tests.
- Cross-workspace, stale-permission, and revoked-access retrieval tests.
- Embedding/model-version coexistence and migration tests.
- Prompt-injection, sensitive-data egress, deletion, and memory-expiry tests.
- Load tests for approved query latency and index freshness SLOs.

**Exit criteria**

- Search quality, latency, deletion, stale-permission, prompt-injection, and
  cross-workspace results meet approved thresholds.
- Retrieval never treats vector similarity as authorization.
- Memory never becomes untraceable operational truth.

### Historical H7: Product cutover (superseded by ADR-033)

**Architecture purpose:**
[Stage H7](ARCHITECTURE_HARDENING.md#stage-h7-core-product-and-migration-cutover)

**Prerequisites**

- H6 exit criteria are met.
- Cutover, restore, reconciliation, compatibility removal, export, and support plans
  are approved.
- Phase 1 migration rehearsal is successful.

**Deliverables**

- Workspace administration and connection-health surfaces.
- Entity, project, task, search, timeline, note, tag, and audit-access surfaces.
- Workspace export and support diagnostics.
- Phase 1 cutover, reconciliation, and compatibility-code removal.

**Required tests**

- End-to-end tests for every migrated Phase 1 capability.
- Workspace administration, export, support-access, and audit-access tests.
- Cutover, rollback or forward-fix, restore, and provider reconciliation rehearsals.
- Accessibility, performance, security, and operational acceptance tests.

**Exit criteria**

- All Phase 1 functionality remains operational through Atlas Core.
- Restore and forward-fix procedures have been exercised successfully.
- Temporary compatibility code is removed or has an approved owner and removal date.

### Historical H8: Recommendations and approvals (superseded by ADR-033)

**Architecture purpose:**
[Stage H8](ARCHITECTURE_HARDENING.md#stage-h8-recommendations-and-basic-approvals)

**Prerequisites**

- H7 exit criteria are met.
- Agent delegation, tool registry, action risk, approval expiry, execution-time policy,
  and AI security specifications are approved.
- Only bounded, measurable use cases are authorized.

**Deliverables**

- Evidence-linked read-only recommendations and user feedback.
- Registered agent tools mapped to the same commands and queries used by humans.
- Single-approver workflow with immutable action digest, expiry, runtime
  preconditions, and execution receipts.
- Budgets, cancellation, outcome verification, and complete audit trail.
- No broad autonomy or direct agent access to databases or provider SDKs.

**Required tests**

- Evidence accuracy, permission filtering, and recommendation evaluation tests.
- Delegation attenuation and tool-permission tests.
- Changed-input, expired-approval, changed-policy, and changed-resource tests.
- Prompt-injection, data-egress, budget, cancellation, and replay tests.
- Tests proving agents cannot bypass commands, validation, approval, or audit.

**Exit criteria**

- Recommendations meet approved quality and safety thresholds.
- Every side effect is authorized at execution time and has a verifiable receipt.
- Agent actions cannot bypass permissions, classification, approvals, command
  validation, or workspace isolation.

## 4. Definition of Ready

A feature MUST NOT begin implementation until all applicable conditions are true:

- The owning bounded context and approved architecture section are identified.
- The Architecture Index and referenced documents have been searched for overlap.
- An accepted ADR exists when the work introduces or fundamentally changes an
  invariant, boundary, data authority, security model, dependency, or platform choice.
- Prerequisite stages and dependencies are complete.
- Workspace ownership, actor, permissions, aggregate, and transaction boundary are
  defined.
- Security, privacy, cross-tenant, provider, and AI data-egress impacts are reviewed.
- Audit events, domain events, idempotency, concurrency, retries, and failure behavior
  are defined.
- Provider/source authority, retention, deletion, and derivative lineage are defined.
- A backward-compatible migration and rollback or forward-fix plan exists.
- Required unit, integration, contract, fitness, adversarial, and end-to-end tests are
  specified.
- There is no unresolved P0 dependency.

Failure of any applicable item returns the feature to architecture or product
clarification. A ticket title or stakeholder request is not architecture authorization.

## 5. Definition of Done

A feature is complete only when all applicable conditions are true:

- The implementation and approved migration are finished.
- Business invariants have automated tests.
- Required unit, integration, contract, fitness, security, migration, and end-to-end
  tests pass in continuous integration.
- Cross-workspace access is denied by application policy and database controls.
- Every material mutation passes authorization and atomically records audit/outbox data.
- Provider operations are idempotent or explicitly classified as non-idempotent with
  safe retry behavior.
- Observability, structured error classification, operational runbooks, and alerts are
  implemented where applicable.
- Documentation is updated without duplicating existing concepts.
- `README_ARCHITECTURE.md` is updated when navigation, status, ownership, or an
  architectural reference changes.
- A new or superseding ADR is linked when a fundamental decision changed.
- Security review is complete and has no unaccepted critical or high finding.
- Migration upgrade, rollback or forward-fix, backfill, and verification are tested.
- No implementation placeholders, disabled required tests, or unresolved work markers
  remain in the change.
- Compatibility code has an accountable owner and removal milestone.

Passing tests alone does not satisfy Done when documentation, security, audit,
operability, or migration obligations are incomplete.

## 6. Coding standards

### Python and typing

- Production Python MUST be fully typed.
- Public functions, methods, ports, DTOs, commands, queries, events, and repository
  interfaces MUST declare input and return types.
- Type checking MUST run in continuous integration.
- Untyped escape hatches require a narrow documented justification.

### Async-first I/O

- Network, database, object storage, provider, and queue I/O MUST use async interfaces.
- CPU-heavy extraction or model work MUST run outside the request event loop.
- Blocking libraries require an explicit adapter and bounded executor strategy.

### Dependency injection

- Application services receive ports, repositories, policy evaluators, clocks, ID
  generators, and external clients through explicit dependency injection.
- Domain logic MUST NOT read global clients, environment variables, request state, or
  provider SDK singletons.
- Tests MUST be able to substitute deterministic fakes at boundaries.

### Domain-driven modules

- Code MUST be organized by bounded context, not by technical layer alone.
- Domain modules own invariants and typed aggregates.
- Application modules orchestrate commands and queries.
- Infrastructure modules implement repositories, provider adapters, queues, and
  framework integration.
- Cross-context writes MUST use approved commands or events, not another module's
  tables.

### Provider neutrality

- Provider names, SDK objects, raw payloads, and provider error types MUST NOT enter
  domain code.
- Canonical models MUST NOT be the accidental union of one provider's schema.
- Provider extensions MUST be explicit, namespaced, and non-authoritative unless an
  approved mapping says otherwise.

### Model ownership and reuse

- A concept has one canonical definition and one owning bounded context.
- API schemas, persistence models, DTOs, and domain models MAY differ only because
  their responsibilities differ; mappings MUST be explicit and tested.
- Copying a model into another module is prohibited.
- Shared primitives MUST remain small, stable, and free of domain behavior.

### Pull-request size

- Pull requests SHOULD represent one reviewable behavior or migration step.
- Schema expansion, backfill, cutover, and contraction SHOULD be separate changes.
- Large generated artifacts, broad formatting, and unrelated refactors MUST be split
  from behavior changes.
- A large pull request requires a written reason and review plan.

### Mandatory tests

- Every behavior requires unit tests for its invariants.
- Every persistence, provider, queue, object-store, authentication, or policy boundary
  requires integration or contract tests.
- Every material user journey requires an end-to-end test at its stage gate.
- Test doubles MUST model documented failure semantics, not only success.

## 7. Migration rules

Atlas migrations MUST preserve existing functionality.

Every migration MUST be:

- backward compatible during rollout;
- reversible where the external side effect is genuinely reversible;
- otherwise protected by a tested forward-fix and compensation plan;
- tested on representative data volume and edge cases;
- documented with owner, scope, duration, observability, and removal milestone.

The required sequence is:

1. **Expand:** add compatible schema, code paths, and instrumentation.
2. **Backfill:** process bounded, resumable, idempotent batches.
3. **Verify:** compare counts, checksums, invariants, permissions, and provider state.
4. **Transition:** use shadow reads, dual reads, or narrowly controlled dual writes.
5. **Cut over:** switch through a reversible control with active monitoring.
6. **Observe:** hold until correctness and SLO thresholds are met.
7. **Contract:** remove old data and code only after the removal gate.

Additional rules:

- Database changes MUST support the currently deployed and immediately previous
  application version during rolling deployment.
- A migration MUST NOT depend on an unbounded table lock or one transaction over the
  full dataset.
- Tenant backfills MUST retain workspace context and produce auditable progress.
- External provider operations MUST use idempotency, preconditions, reconciliation,
  and receipts where supported.
- Data loss, permission broadening, credential exposure, or irreversible provider
  mutation requires explicit approval and a recovery plan.

## 8. Approval rules

High-risk operations require explicit, action-specific approval before execution and
runtime policy re-evaluation immediately before the side effect.

High-risk operations include:

- sending email or messages;
- deleting or externally sharing files;
- creating, updating, cancelling, or deleting calendar events;
- changing memberships, roles, permissions, credentials, or workspace policy;
- financial commitments, payments, refunds, or ledger-affecting actions;
- publishing content or communicating as a person or company;
- bulk export, retention override, legal-hold change, or destructive migration;
- autonomous agent actions with external or irreversible effects.

Approval MUST:

- identify workspace, actor, approver, command, normalized inputs, target resources,
  risk class, and expiry;
- bind to an immutable action digest;
- be invalidated by material input, policy, permission, target-version, or context
  changes;
- never substitute for authorization;
- be evaluated again at execution time;
- produce an immutable execution receipt with outcome and verification;
- use compensation when a true rollback is impossible.

Read-only actions MAY still require approval when classification, privacy, volume,
cross-workspace sharing, or data egress makes them high risk.

Relevant decisions:
[ADR-010](DECISIONS.md#adr-010-agents-use-the-same-application-commands-as-humans) and
[ADR-011](DECISIONS.md#adr-011-approval-binds-to-an-immutable-action-digest).

## 9. Architecture governance

No implementation may violate:

- [README_ARCHITECTURE.md](README_ARCHITECTURE.md);
- [ARCHITECTURE.md](ARCHITECTURE.md);
- [DECISIONS.md](DECISIONS.md);
- higher-priority hardening and security constraints linked from the Architecture
  Index.

Before changing code, an engineer MUST:

1. locate the authorizing section through the Architecture Index;
2. search all referenced documents for the concept and terminology;
3. identify the owning context and relevant ADRs;
4. report inconsistencies, duplication, or drift;
5. resolve architecture conflicts before implementation.

When a fundamental implementation need conflicts with architecture:

1. stop implementation;
2. document the problem, alternatives, security impact, migration, and consequences;
3. add a new ADR that supersedes rather than rewrites historical rationale;
4. update all affected architecture documents and the Architecture Index;
5. add or update architecture fitness tests;
6. resume implementation only after approval.

Architecture documentation is one coherent system. Knowledge MUST be consolidated at
its owning document and linked elsewhere; parallel definitions are prohibited.

## 10. Pull request engineering contract

Every pull request MUST answer:

1. **Why is this needed?**
2. **Which document and section authorize it?**
3. **Which ADR supports it, or why is no ADR required?**
4. **How is it tested, including negative and cross-workspace paths?**
5. **How can it be rolled back or safely forward-fixed?**

Every pull request MUST also declare:

- owning bounded context and workspace impact;
- security, privacy, provider, data-retention, and AI impact;
- schema, event, API, and compatibility impact;
- audit and observability behavior;
- deployment, verification, and removal plan;
- current H0–H8 stage and the stage exit criterion it advances.

A reviewer MUST reject a change that lacks traceability, violates a stage gate, weakens
tenant isolation, bypasses commands or policy, leaks provider concepts, duplicates a
model, omits required tests, or cannot explain recovery.

## 11. Final engineering rule

Code is not the source of architectural authority.

No pull request may merge unless its need, architectural authorization, ADR basis,
tests, security properties, audit behavior, and recovery path are explicit and
reviewable.

If Atlas cannot explain why a change is permitted and how it fails safely, Atlas is not
ready to ship that change.
