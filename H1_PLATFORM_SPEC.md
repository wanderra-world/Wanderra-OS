# H1 Platform Skeleton Specification

Canonical implementation decomposition for Atlas Phase 2 Stage H1.

**Owner:** Atlas Core
**Status:** Accepted
**Stage:** H1 — Platform skeleton
**Architecture entry point:** [README_ARCHITECTURE.md](README_ARCHITECTURE.md)
**Engineering gate:** [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#h1)

This document owns the H1 slice sequence and slice-level scope. It does not redefine
domain terminology, architecture decisions, stage exit criteria, or engineering
workflow. Those remain owned by the documents linked through the Architecture Index.

Approval of this specification authorizes one slice at a time in the order defined
here. A later slice is not authorized merely because an earlier slice is complete.

## 1. H1 objective

H1 establishes the production security and tenancy skeleton used by every later Atlas
Core bounded context:

- organization and workspace ownership;
- canonical identity and revocable sessions;
- workspace memberships and fixed role templates;
- deterministic authorization;
- transaction-local workspace and actor context;
- composite tenant keys and forced PostgreSQL RLS;
- managed per-record envelope encryption;
- immutable audit and transactional outbox/inbox;
- recovery, restore, and workspace-foundation deletion evidence.

The canonical H1 deliverables, required tests, and exit criteria remain in
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#h1). The purpose and position of H1
remain in
[ARCHITECTURE_HARDENING.md](ARCHITECTURE_HARDENING.md#stage-h1-platform-skeleton).

## 2. H1 boundaries

H1 is a platform-foundation stage, not a business-feature stage.

H1 MUST NOT implement:

- provider-neutral connections or migrate Gmail, Calendar, or Drive; those belong to
  H2 and H4;
- universal entities or typed operational core projections; those belong to H3;
- a permanent durable-job technology or provider synchronization workers; those
  belong to H4;
- documents, extraction, source custody, or derivative processing; those belong to H5;
- memory, embeddings, pgvector, ingestion, or unified search; those belong to H6;
- recommendations, agents, or approval-controlled automation; those belong to H8;
- custom roles, groups, cross-workspace reasoning, microservices, or generalized
  knowledge graphs.

Phase 1 API behavior remains backward compatible throughout H1. New H1 paths remain
unused by Phase 1 requests until their explicit migration stage.

## 3. Cross-slice constraints

Every H1 slice MUST:

1. preserve the Formal H0 Exit invariants and merge-blocking fitness gate;
2. use additive expand-and-contract migrations with tested downgrade or proven
   forward-fix;
3. keep Google and all other provider types outside Atlas Core models and services;
4. deny access when workspace, actor, session, policy, or tenant context is missing or
   invalid;
5. use workspace-inclusive candidate keys and composite foreign keys for tenant-owned
   relations;
6. enable and force RLS on tenant-owned tables before runtime access;
7. write security-relevant state, audit, and outbox records atomically;
8. add negative, cross-workspace, concurrency, revocation, and rollback tests where
   applicable;
9. leave no compatibility path without an owner and removal stage;
10. update `PROJECT_STATUS.md` only after verification.

No H1 slice may weaken branch protection, the `H0 Required Gate`, threat controls, or
architecture fitness rules.

## 4. Canonical H1 sequence

| Slice | Name | Status | Primary outcome |
|---|---|---|---|
| H1-01 | Organization and workspace schema expansion | Accepted; merged in PR #1 | Additive organization, ownership, workspace, placement, audit, and outbox foundation |
| H1-02 | Canonical identity and external identity schema | Accepted; merged in PR #3 | Global users and issuer/subject identity links with safe migration |
| H1-03 | Revocable session and identity lifecycle | Accepted; merged in PR #4 | Server-side sessions, invitations, recovery, strong-authentication state, and revocation |
| H1-04 | Workspace memberships and fixed roles | Accepted; merged in PR #5 | Workspace access lifecycle and versioned fixed-role assignments |
| H1-05 | Deterministic authorization boundary | Accepted; merged in PR #6 | Deny-first fixed-role decisions with reason codes |
| H1-06 | Request, actor, tenant, and repository context | Accepted; merged in PR #7 | Typed execution context, transaction-local PostgreSQL context, runtime roles, and repository enforcement |
| H1-07 | Managed envelope encryption foundation | Accepted; merged in PR #8 | KMS-backed per-record encryption and safe Phase 1 credential migration tooling |
| H1-08 | Immutable audit and transactional messaging | Implemented; pending pull-request review | Production audit writer, outbox/inbox, idempotency, sequencing, and tamper-evidence baseline |
| H1-09 | Foundation recovery, restore, and closure rehearsal | Proposed | Backup/restore, tenant-foundation deletion, closure receipts, and recovery evidence |
| H1-10 | Synthetic tenant vertical slice and Formal H1 Exit | Proposed | Integrated proof of every H1 exit criterion and security acceptance |

The sequence is mandatory. Parallel implementation is prohibited when a slice depends
on an incomplete predecessor. Documentation and disposable test design may be prepared
early, but cannot be represented as production completion.

## 5. Slice specifications

### H1-01: Organization and workspace schema expansion

**Status:** Accepted; merged in pull request #1.

**Objective**

Create the additive organization, organization ownership, workspace, and placement
foundation, including deterministic default ownership for existing Phase 1 users.

**Boundaries**

- No request authentication or authorization.
- No Phase 1 repository migration.
- No provider, entity, memory, search, or agent changes.

**Dependencies**

- Formal H0 Exit;
- ADR-021, ADR-022, ADR-020, ADR-029, and ADR-031.

**Acceptance**

- Migration, backfill, forced RLS, ownership invariants, audit/outbox bootstrap,
  downgrade, full regression, Docker, and CI evidence pass.
- Existing Phase 1 runtime behavior remains unchanged.

### H1-02: Canonical identity and external identity schema

**Status:** Implemented on `codex/h1-02-canonical-identity`; pending pull-request
review.

**Objective**

Separate Atlas global human identity from login-provider identity and prepare existing
Phase 1 users for safe canonical identity use.

**Scope**

- Evolve `users` into the canonical global identity record without assigning tenant
  data ownership to it.
- Add external identity links keyed uniquely by issuer and subject.
- Record verified email as an attribute with verification provenance; never use email
  to merge accounts automatically.
- Add identity lifecycle status, creation/update timestamps, and optimistic version.
- Backfill existing Phase 1 users without changing their UUIDs or integration foreign
  keys.
- Emit atomic audit and outbox evidence for migrated identities.

**Boundaries**

- No login endpoint, cookie, session, invitation, recovery, MFA, or account-linking
  workflow.
- No workspace membership or permission assignment.
- No provider business-account connection model; that belongs to H2.
- No automatic deduplication or merge based on email.

**Dependencies**

- H1-01 merged and migrated;
- ADR-023, ADR-020, ADR-029, and the identity contract in
  `H0_FOUNDATION_SPEC.md`.

**Acceptance criteria**

- Existing user IDs and Gmail, Calendar, Drive, project, and conversation references
  remain valid through upgrade and downgrade or documented forward-fix.
- Duplicate issuer/subject links are rejected.
- Duplicate verified email across different identities does not merge or reject valid
  identities.
- Identity state, audit, and outbox writes are atomic.
- Migration is idempotent and passes empty, single-user, and multi-user fixtures.
- No production authentication behavior changes.

**Acceptance evidence**

- [Canonical identity model tests](tests/identity/test_h1_02_models.py)
- [PostgreSQL compatibility, atomicity, idempotency, and rollback tests](tests/identity/test_h1_02_migration.py)
- [Additive H1-02 migration](alembic/versions/0007_add_canonical_identity.py)

### H1-03: Revocable session and identity lifecycle

**Status:** Implemented; pending pull-request review.

**Objective**

Implement the server-side identity lifecycle needed to authenticate and revoke human
access safely.

**Scope**

- Opaque hashed server-side sessions with device, authentication-strength, expiry,
  last-seen, and revocation metadata.
- External identity linking records with reversible review state.
- Hashed, scoped, expiring, single-use invitations and recovery tokens.
- Recovery-driven invalidation of sessions and recovery material.
- Recent-authentication and MFA state representation.
- Security notification and audit/outbox records.

**Boundaries**

- One OIDC integration may be used to prove the canonical contract, but provider SDK
  types remain inside the identity adapter.
- No workspace permissions beyond invitation target metadata.
- No broad service-principal or agent identity framework.
- No custom authentication protocol.

**Dependencies**

- H1-02;
- ADR-023, ADR-029, ADR-030, and H0 identity lifecycle evidence.

**Acceptance criteria**

- Raw session, invitation, and recovery tokens never persist.
- Revocation takes effect on the next transaction.
- Expired, replayed, revoked, or wrong-purpose tokens deny access.
- Recovery invalidates all required credentials atomically.
- Identity linking requires proof of both identities and recent strong authentication.
- Cookie settings and CSRF/session fixation defenses pass security tests.
- Concurrency tests prove single-use token behavior.

**Acceptance evidence**

- [Lifecycle security and schema contract tests](tests/identity/test_h1_03_lifecycle_unit.py)
- [PostgreSQL, RLS, rollback, revocation, recovery, and concurrency tests](tests/identity/test_h1_03_lifecycle_postgres.py)
- [Additive H1-03 migration](alembic/versions/0008_add_identity_lifecycle.py)

### H1-04: Workspace memberships and fixed roles

**Status:** Implemented; pending pull-request review.

**Objective**

Connect canonical identities to workspaces through explicit lifecycle-controlled
memberships and versioned fixed role templates.

**Scope**

- Workspace membership state and version.
- Fixed role templates:
  `organization_owner`, `organization_admin`, `workspace_owner`,
  `workspace_admin`, `member`, and `viewer`.
- Explicit workspace role assignments and capability catalog.
- Membership invitation acceptance handoff from H1-03.
- Immediate membership/role revocation metadata.
- Last-workspace-owner and personal-organization consistency enforcement.

**Boundaries**

- Organization administration does not imply workspace content access.
- No custom roles, groups, nested teams, or arbitrary policy language.
- No exceptional grants or break-glass execution; H1-05 owns policy evaluation.
- No provider permissions.

**Dependencies**

- H1-01, H1-02, and H1-03;
- ADR-021, ADR-024, and the authorization contract in
  `H0_FOUNDATION_SPEC.md`.

**Acceptance criteria**

- Every workspace retains at least one active workspace owner.
- Personal organization/workspace invariants remain enforced.
- Revoked or inactive memberships cannot receive effective capabilities.
- Fixed-role definitions are versioned and deterministic.
- Organization administrators have no implicit content access.
- Cross-workspace role assignment and composite-key attacks fail.

**Acceptance evidence**

- [Membership model and fixed-role contract tests](tests/memberships/test_h1_04_models.py)
- [PostgreSQL, RLS, rollback, lifecycle, and concurrency tests](tests/memberships/test_h1_04_postgres.py)
- [H1-04 membership-only architecture fitness tests](tests/architecture/test_h1_04_membership_scope.py)
- [Additive H1-04 migration](alembic/versions/0009_add_workspace_memberships.py)

### H1-05: Deterministic authorization boundary

**Status:** Implemented; pending pull-request review.

**Objective**

Provide one explainable, deny-first authorization service for every Atlas Core command
and query.

**Scope**

- Versioned policy input/output contracts.
- Fixed-role capability evaluation.
- Deny precedence for invalid identity/session/membership, workspace mismatch, legal or
  security restriction, and missing grants.
- Reason codes, obligations, and policy version on every decision.
- Capability-specific, expiring exceptional grants.
- Break-glass decision contract with incident, approver, scope, expiry, notification,
  and audit requirements.

**Boundaries**

- Approval never creates permission.
- No custom role editor or general-purpose ABAC policy language.
- No provider call or resource repository is migrated yet.
- No agent authorization.

**Dependencies**

- H1-03 and H1-04;
- ADR-024, ADR-011, ADR-018, and H0 authorization evidence.

**Acceptance criteria**

- The approved authorization decision matrix passes.
- Missing input and unknown capability deny.
- Explicit deny always overrides grants and obligations.
- Revocation is visible without positive authorization caching across transactions.
- Decisions are deterministic for identical versioned inputs.
- Every decision can be safely audited without sensitive payload leakage.

**Acceptance evidence**

- [Authorization model and decision-contract tests](tests/authorization/test_h1_05_models.py)
- [PostgreSQL, RLS, rollback, revocation, and decision-matrix tests](tests/authorization/test_h1_05_postgres.py)
- [H1-05 slice-isolation architecture fitness tests](tests/architecture/test_h1_05_authorization_scope.py)
- [Additive H1-05 permission migration](alembic/versions/0010_add_fixed_role_permissions.py)

### H1-06: Request, actor, tenant, and repository context

**Status:** Implemented; pending pull-request review.

**Objective**

Carry authenticated actor and workspace authority from the application boundary into
transactions, repositories, audit, events, and future job envelopes.

**Scope**

- Typed request, actor, organization, workspace, delegation, and correlation context.
- Transaction-local `atlas.workspace_id` and actor settings.
- Production database roles for migrator, runtime, worker, audit writer, and support
  boundaries.
- Repository base contract that requires explicit workspace context.
- Pool checkout/reset safeguards and placement-aware routing contract for the primary
  cell.
- Fitness tests that reject context-free tenant repository methods.

**Boundaries**

- Apply the repository contract only to H1-owned paths; Phase 1 provider repositories
  migrate in H2.
- Define future job context envelopes but do not select or implement the durable job
  platform.
- No cross-workspace support console or standing support access.
- No cell sharding.

**Dependencies**

- H1-05;
- ADR-022, ADR-024, ADR-029, ADR-032, and H0 tenancy evidence.

**Acceptance criteria**

- Missing, malformed, stale, or cross-workspace context denies before repository
  access.
- Runtime and worker roles cannot bypass RLS or own tenant tables.
- Pool reuse cannot retain workspace or actor context.
- Composite-key attacks across reads, writes, joins, uniqueness, exports, and future
  job envelopes fail.
- Correlation and authorization decision references reach audit and outbox records.
- Existing Phase 1 routes remain unchanged.

**Acceptance evidence**

- [Immutable execution-context and repository-contract tests](tests/execution_context/test_h1_06_context.py)
- [PostgreSQL, RLS, role, replay, pool-reset, and rollback tests](tests/execution_context/test_h1_06_postgres.py)
- [H1-06 slice-isolation architecture fitness tests](tests/architecture/test_h1_06_execution_context_scope.py)
- H1-06 is schema-free: it reuses migration `0010_h1_authorization`, and rollback
  rehearsal proves the existing H1-05 boundary remains reversible.

### H1-07: Managed envelope encryption foundation

**Status:** Implemented; pending pull-request review.

**Objective**

Replace single-key credential protection with a production KMS-backed, per-record
envelope-encryption service and reversible migration tooling.

**Scope**

- KMS port and one production adapter selected by deployment environment.
- Per-record authenticated encryption with wrapped DEKs and versioned metadata.
- Tenant-bound authenticated additional data.
- KEK rewrap, resumable DEK rotation, failure quarantine, and emergency disable.
- Additive columns and shadow verification for existing Google credentials.
- Migration inventory, checksum, re-encryption, cutover flag, and reauthorization
  fallback.

**Boundaries**

- No connection unification or provider-neutral credential aggregate; H2 owns that
  migration.
- No plaintext credentials in logs, events, audit, errors, or test fixtures.
- No destructive removal of legacy ciphertext during H1.
- No KMS administration capability in runtime roles.

**Dependencies**

- H1-01 and H1-06;
- ADR-025, ADR-020, P1.12 migration rehearsal requirements, and H0 encryption
  evidence.

**Acceptance criteria**

- Ciphertext cannot be moved across workspace, record, connection, or record type.
- KEK rewrap and DEK replacement resume safely after interruption.
- KMS outage, wrong key version, corrupted ciphertext, and revoked access fail closed.
- Existing credentials shadow-decrypt equivalently before cutover.
- Rollback or forward-fix preserves provider access.
- Rotation, audit, least-privilege, and secret-leak tests pass.

**Acceptance evidence**

- [Envelope and managed-KMS contract tests](tests/encryption/test_h1_07_contracts.py)
- [Migration, RLS, rotation, failure, audit, and rollback tests](tests/encryption/test_h1_07_postgres.py)
- [H1-07 encryption-only architecture fitness tests](tests/architecture/test_h1_07_encryption_scope.py)
- [Additive managed-envelope and legacy-shadow migration](alembic/versions/0011_add_managed_envelopes.py)

### H1-08: Immutable audit and transactional messaging

**Objective**

Turn the H1-01 bootstrap tables into the production accountability and reliable
domain-event path.

**Scope**

- Append-only audit writer and separately restricted readers.
- Minimal, redacted audit payload with actor, workspace, action, target, decision,
  correlation, outcome, and safe digest.
- Transactional outbox/inbox with workspace, aggregate sequence, schema version,
  idempotency, gap handling, quarantine, and authorized replay.
- Optimistic concurrency and caller-owned idempotency records for H1 commands.
- Tamper-evidence baseline using hash chaining or signed checkpoints and periodic
  verification.
- Retention and partition-readiness metadata without premature partitioning.

**Boundaries**

- No external broker or permanent durable-job selection.
- No user-facing timeline projection.
- No provider side effects.
- Audit is not an event-replay source and outbox is not the audit log.

**Dependencies**

- H1-05, H1-06, and H1-07;
- ADR-007, ADR-008, ADR-017, ADR-029, P1.2, P1.8, and H0 replay evidence.

**Acceptance criteria**

- State, audit, outbox, and idempotency commit or roll back atomically.
- Duplicate commands and events do not duplicate state or effects.
- Out-of-order events are detected and quarantined.
- Audit UPDATE/DELETE is impossible for runtime and audit-writer roles.
- Tampering is detectable by verification evidence.
- Replay requires explicit authorization and cannot cross workspaces.
- Schema compatibility and poison-message tests pass.

**Acceptance evidence**

- [Deterministic command and event contract tests](tests/messaging/test_h1_08_contracts.py)
- [PostgreSQL atomicity, idempotency, concurrency, replay, RLS, tamper, and rollback tests](tests/messaging/test_h1_08_postgres.py)
- [H1-08 slice-isolation architecture fitness tests](tests/architecture/test_h1_08_messaging_scope.py)
- [Additive audit and messaging migration](alembic/versions/0012_add_audit_messaging.py)

### H1-09: Foundation recovery, restore, and closure rehearsal

**Objective**

Prove that the H1 platform skeleton can be recovered, closed, and deleted without
losing isolation or accountability.

**Scope**

- Encrypted PostgreSQL backup and isolated restore procedure for H1 data.
- KMS/key-access recovery procedure and failure evidence.
- Synthetic workspace export manifest for H1-owned records.
- Workspace-foundation closure state machine: freeze writes, revoke H1 sessions and
  memberships, apply retention/legal hold, erase eligible H1 data, verify, and issue a
  closure receipt.
- Recovery-point and recovery-time instrumentation against approved H0 targets.
- Provider reconciliation recorded as an H2 dependency, not executed in H1.

**Boundaries**

- Export and deletion cover only H1-owned data.
- No provider deletion, document lineage, or content-bundle export.
- No workspace transfer or cell migration.
- No claim that Phase 1 provider data is fully closed before H2/H5.

**Dependencies**

- H1-03 through H1-08;
- ADR-020, ADR-021, ADR-022, ADR-027, P1.4, P1.14, and H0 recovery targets.

**Acceptance criteria**

- Backup restores into an isolated environment with verified row counts and digests.
- Restored RLS, roles, encryption access, audit verification, and outbox state remain
  correct.
- Closure blocks new H1 writes and revokes access immediately.
- Legal hold and minimum retention override erasure.
- Eligible H1 derivatives and credentials are deleted or cryptographically
  inaccessible with a verification receipt.
- Repeated closure and restore operations are idempotent.

### H1-10: Synthetic tenant vertical slice and Formal H1 Exit

**Objective**

Integrate H1 controls and determine whether the platform skeleton is safe to authorize
H2.

**Scope**

- Create two synthetic organizations, workspaces, users, identities, sessions,
  memberships, and role assignments.
- Execute authorized and adversarial commands through the real H1 application,
  policy, repository, database, audit, and event boundaries.
- Exercise revocation, idempotency, concurrency, backup, restore, closure, and
  deletion.
- Run the complete H0/H1 regression, architecture fitness, migration, Docker, and
  security suites.
- Produce the H1 evidence matrix and formal security review.

**Boundaries**

- Evidence and defect remediation only; no H2 feature implementation.
- No provider migration, universal entity, memory, search, or agent work.
- Any architecture-changing remediation requires a superseding ADR before code.

**Dependencies**

- H1-01 through H1-09 complete and merged.

**Acceptance criteria**

- Every H1 prerequisite, deliverable, required test, and exit criterion in
  `IMPLEMENTATION_GUIDE.md` is accepted with evidence.
- Synthetic tenant isolation, revocation, audit, idempotency, backup, restore,
  closure, and deletion pass.
- No H1-owned repository accepts tenant access without explicit workspace context.
- No unresolved critical or high security finding lacks explicit, time-bounded risk
  acceptance.
- Phase 1 regression and Google integration behavior remain compatible.
- The merge-blocking CI gate is green and Formal H1 Exit is explicitly accepted before
  H2 begins.

## 6. Dependency flow

```text
H1-01 Organization/workspace
  |
  v
H1-02 Canonical identity
  |
  v
H1-03 Sessions/lifecycle
  |
  v
H1-04 Memberships/roles
  |
  v
H1-05 Authorization
  |
  v
H1-06 Execution context/RLS
  |
  v
H1-07 Envelope encryption
  |
  v
H1-08 Audit/outbox/inbox
  |
  v
H1-09 Recovery/closure
  |
  v
H1-10 Formal H1 Exit
```

## 7. Review decisions requested

Architecture reviewers must explicitly accept or revise:

1. the H1-02 through H1-10 ordering;
2. the boundary between H1 context contracts and H4 durable-job implementation;
3. the boundary between H1-owned repository enforcement and H2 Phase 1 migration;
4. the H1-07 shadow migration without legacy ciphertext removal;
5. the H1-08 tamper-evidence baseline;
6. the H1-09 limitation to H1-owned recovery and closure;
7. the requirement that H1-10, rather than an implementation slice, authorizes H2.

This specification was accepted through pull request #2. Each later slice becomes
eligible only after its predecessor is accepted and the user explicitly authorizes
that slice.
