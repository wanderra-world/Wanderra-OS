# H0 Foundation Specification

Normative specification for the Atlas Architecture Hardening stage.

**Status:** Approved for H0 validation  
**Scope:** P0.1–P0.14  
**Owner:** Atlas Core  
**Architecture entry point:** [README_ARCHITECTURE.md](README_ARCHITECTURE.md)  
**Decision record:** [DECISIONS.md](DECISIONS.md#h0-superseding-decisions)

This document owns the implementable P0 contracts. Other architecture documents link
to it instead of repeating these details. Approval authorizes H0 prototypes and
architecture fitness tests. It does not authorize production Phase 2 schemas or
features before the H0 exit evidence in section 17 is accepted.

## 1. H0 scope and non-goals

H0 proves that Atlas Core security and consistency boundaries are implementable before
production development.

H0 includes specifications and disposable prototypes for tenancy, authorization,
encryption, provider conflicts, events, migration safety, and fitness tests.

H0 excludes production features and migrations, broad business modules, generalized
knowledge graphs, autonomous agents, a public provider SDK, microservices, and
multi-cell deployment. Prototype artifacts must remain isolated from production
migrations.

## 2. Tenant key and database isolation

Every tenant-owned relation has:

- `workspace_id UUID NOT NULL`;
- an object identifier unique within its workspace;
- a candidate key `UNIQUE (workspace_id, id)`;
- composite foreign keys that include `workspace_id`;
- a placement reference whose initial value resolves to the primary cell.

Global identifiers do not remove the composite-key requirement.

Database roles are:

- `atlas_migrator`, which owns DDL and never serves application traffic;
- `atlas_runtime`, the non-bypass-RLS API role;
- `atlas_worker`, the non-bypass-RLS job role;
- `atlas_audit_writer`, with append-only audit capability;
- `atlas_support`, with no standing tenant access.

Table owners and `BYPASSRLS` roles are prohibited from application pools.

Every tenant transaction sets `atlas.workspace_id` and actor metadata with
transaction-local PostgreSQL settings. Repositories reject calls without explicit
typed workspace context. Pool checkout begins without tenant context; transaction
completion resets it. Connection-level tenant state is prohibited.

RLS compares row workspace to transaction-local workspace and denies missing or invalid
context. Cross-workspace administration uses separate, audited commands and roles.

Every workspace has a `cell_id`. H1 uses one primary cell, while repository and routing
contracts accept placement explicitly. Sharding is deferred until justified.

## 3. Organization and workspace ownership

Every workspace belongs to exactly one `business` or `personal` organization. A
Personal workspace belongs to a single-member personal organization and is not a
tenancy exception.

Organizations retain at least one active owner. Removing the last owner is rejected.
Organization administrators manage administration but receive no implicit workspace
content access; access requires membership or an audited break-glass grant.

Workspace transfer is prohibited in Phase 2. A future transfer protocol requires a new
ADR. Workspace closure freezes writes, revokes connections and sessions, applies legal
hold and retention, deletes eligible sources and derivatives, verifies provider
actions, and issues a closure receipt.

## 4. Identity and session lifecycle

Atlas uses a canonical global `User` and separate external identity links. Business
provider accounts are connections, not login identities.

- Authentication uses OIDC Authorization Code Flow with PKCE.
- Atlas uses opaque server-side sessions in secure, `HttpOnly`, `SameSite=Lax` cookies.
- Only hashed session tokens are stored with user, device, authentication strength,
  expiry, and revocation metadata.
- Privileged operations require recent authentication and MFA.
- Revocation applies on the next command or query; positive authorization is not cached
  beyond the transaction.
- External identities are unique by issuer and subject.
- Verified email is an attribute and never causes automatic account merging.
- Identity linking requires recent strong authentication, proof of both identities,
  audit, and a reversible review window.
- Invitations are hashed, single-use, scoped, authority-rechecked, and expire within
  72 hours.
- Recovery invalidates sessions and recovery tokens and emits security notifications.
- Service, support, and agent identities have explicit scope, owner, expiry, and
  revocation.

## 5. Authorization contract

Authorization is deny by default and runs at each application command/query boundary
before repository or provider access.

Decision input contains actor, session, authentication strength, organization,
workspace, membership, fixed-role permissions, resource attributes, requested
operation, risk, delegation, approval, connection, and request context.

The output is `allow` or `deny` with reason codes, policy version, and obligations.
Precedence is:

1. invalid or revoked identity, session, membership, or delegation denies;
2. workspace mismatch denies;
3. legal, classification, and security denies apply;
4. a fixed-role permission must grant the capability;
5. context and resource grants narrow access;
6. approval and step-up obligations must be satisfied;
7. absence of an allow denies.

Approval never grants permission.

Initial roles are `organization_owner`, `organization_admin`, `workspace_owner`,
`workspace_admin`, `member`, and `viewer`. They are fixed, versioned templates. Custom
roles and groups are deferred. Exceptional grants are explicit, capability-specific,
audited, and expiring when elevated.

Revocation affects new transactions immediately. Jobs re-evaluate authority before
material side effects. Break-glass access requires an incident, approver, narrow scope,
short expiry, notification, and complete audit.

## 6. Threat model and mitigation register

Trust boundaries include client/API, API/database, Atlas/external services, provider
webhooks, untrusted content/extraction/model context, intent/commands/side effects, and
operator/tenant resources.

Protected assets include tenant data, identities, provider credentials, documents and
derivatives, audit evidence, encryption keys, backups, availability, quotas, and
external-action integrity.

| ID | Threat | Primary controls |
|---|---|---|
| T01 | Cross-workspace access | Composite keys, RLS, typed context, adversarial tests |
| T02 | Pool leaks tenant context | Transaction-local settings, non-bypass roles, reset tests |
| T03 | Account takeover or stale authority | OIDC PKCE, MFA, revocation, step-up |
| T04 | Provider credential theft | Envelope encryption, KMS policy, audit, rotation |
| T05 | Forged/replayed webhook | Signatures, time window, deduplication, routing |
| T06 | Provider conflict overwrites truth | Authority, etags, preconditions, conflict state |
| T07 | Malicious document or prompt | Quarantine, trust labels, instruction isolation |
| T08 | Sensitive model egress | Minimization, classification routing, redacted logs |
| T09 | Agent bypass | Registered tools, commands, delegation, runtime approval |
| T10 | Incomplete deletion | Lineage, erasure workflow, verification receipt |
| T11 | Replay duplicates effects | Idempotency, inbox, sequence, preconditions |
| T12 | Privileged audit tampering | Append-only role, chained export, verification |
| T13 | Support abuse | No standing access, break-glass approval, notification |
| T14 | Resource/quota exhaustion | Limits, bounded payloads, fairness, alerts |

An unresolved critical threat requires named ownership, compensating controls, expiry,
and explicit acceptance. H0 cannot exit with an unaccepted critical threat.

## 7. Versioned envelope encryption

Provider credentials use per-record authenticated encryption. A managed KMS
key-encryption key wraps each data-encryption key.

Encrypted records retain algorithm/format version, ciphertext, nonce, wrapped key, KMS
key/version, workspace/connection identifiers, and rotation timestamps. Authenticated
additional data binds ciphertext to workspace, connection, record type, and record ID.

Runtime roles can request narrow decrypt operations but cannot administer KMS keys.
Plaintext credentials and keys never enter logs, events, audit payloads, or errors.
Rotation supports KEK rewrap and resumable DEK replacement. Emergency handling
disables keys or connections, revokes provider tokens, invalidates clients, and records
an incident. Phase 1 migration follows expand, re-encrypt, verify, cut over, contract.

## 8. Object storage and document custody

Atlas uses an S3-compatible object-storage port selected by environment, never exposed
to domain code. Document content is immutable and content-addressed. Object placement
uses a non-guessable tenant partition but never relies on path secrecy for access.

Required controls are managed encryption, TLS, content hashes, quarantine, MIME
validation, malware scanning, short-lived signed access after authorization, regional
placement, legal hold, lifecycle, backup, and deletion policy. Public buckets and
permanent signed URLs are prohibited.

PostgreSQL stores metadata and custody state, not ordinary document blobs. A version
becomes readable only after upload, hash verification, scanning, and atomic metadata
promotion. Abandoned quarantine objects expire.

## 9. Provider mirror, authority, and conflict model

Capability contracts and synchronization contracts are separate.

A provider mirror stores workspace, connection, resource type, external ID, canonical
reference, provider version/etag and timestamps, normalized hash, governed raw-payload
reference, sync state, tombstone, authority policy, and conflict state. Its unique key
is `(workspace_id, connection_id, resource_type, external_id)`.

Authority is explicit per resource or field: `provider_authoritative`,
`atlas_authoritative`, `user_resolved`, or `mergeable`. Provider resources remain
mirrors until an approved command maps or promotes them.

Inbound updates compare versions and authority. Ambiguity enters conflict state;
destructive last-write-wins is prohibited. Outbound writes use provider preconditions,
stable idempotency keys, and post-write verification. Failed preconditions refresh and
resolve rather than blindly retry.

Provider deletion creates a tombstone; it does not automatically erase governed Atlas
evidence. Atlas deletion is a separate policy-controlled command with verification.

## 10. Retention, deletion, and derivative lineage

Every derivative records direct sources, derivation type, tool/model version, creation
time, policy/classification version, and content hash when applicable.

Lineage covers provider mirrors/raw payloads, document versions/chunks, extracted
attributes/claims, timeline/search projections, embeddings, memory, notes, caches,
exports, and traceable backups.

Policy precedence is legal hold, statutory/contractual minimum, approved security
preservation, workspace policy, then user deletion or expiry.

Tombstoning stops ordinary access and new derivation. An idempotent erasure workflow
traverses lineage, deletes eligible data, invalidates indexes/caches, invokes providers
only when policy requires it, and issues a verification receipt. Audit retains minimal
accountability evidence. Backups expire under schedule or become inaccessible through
key erasure where applicable.

## 11. AI security and data egress

Provider and user content is untrusted data, never trusted instruction.

AI context starts with one workspace and authorized actor; filters current permission
and classification before retrieval; minimizes content; preserves source/trust labels;
separates instructions from content; and excludes secrets and unsupported classes.

Model routes are approved by classification, region, retention, training policy, and
capability. Model providers must not train on Atlas data where contractual controls
exist. Logs are policy-limited and redacted.

Model output acts only through registered commands/queries with runtime authorization,
delegation, approval, resource-version, and budget checks. Retrieved content cannot
expand tool permissions. Cross-workspace context is denied without a precise sharing
grant. AI release requires prompt-injection, exfiltration, poisoned-content,
stale-permission, and cross-workspace tests.

## 12. Universal entity and projection integrity

Only these Phase 2 aggregates may receive entity identities:

- contact/person;
- company;
- project;
- task;
- communication/message;
- meeting/calendar event;
- document/file.

Organizations, workspaces, identities, memberships, connections, credentials, policies,
events, audit, jobs, and infrastructure records are not universal entities merely
because they can be referenced.

Entity types come from a versioned Atlas-controlled registry. A typed aggregate and its
entity row are created in one transaction. Exactly one active typed projection exists
where required. Direct registry insertion is prohibited.

Relationships validate endpoint types, workspace equality, cardinality, direction, and
lifecycle. Cross-workspace relationships are deferred. Deletion starts in the owning
aggregate and applies policy to projections, relationships, and generic capabilities.
Entity type changes require migrations.

## 13. Minimum canonical core

Phase 2 core is limited to:

- organizations, workspaces, identities, sessions, memberships, roles, and policies;
- connections, credentials, OAuth transactions, mirrors, and external references;
- entity registry and relationships;
- contacts, companies, projects, and tasks;
- communications, calendar events, documents, and provider file placements;
- tags, attachments, ownership, and exceptional grants;
- events, outbox/inbox, jobs, timeline, and audit;
- permission-aware search and governed memory.

Finance, shipments, properties, vehicles, commerce, CRM-specific aggregates,
generalized knowledge graphs, custom roles, cross-workspace collaboration, advanced
workflows, and broad agents are later modules.

PostgreSQL is the initial record and search platform. Extraction requires measured SLO,
scale, isolation, or team-ownership evidence and a new ADR.

## 14. Event, idempotency, and concurrency contract

Events contain event ID/type/schema version, workspace, aggregate type/ID/sequence,
actor/delegation, correlation/causation, timestamps, classification, and payload.

Commands use expected aggregate versions. State, audit, and outbox commit atomically.
Consumers own inbox deduplication and process at least once. Ordering-sensitive
consumers detect sequence gaps and wait for repair.

Schemas are additive within a major version. Breaking meaning creates a new type or
major version with compatibility/replay plan. Unknown versions are quarantined; poison
events enter an operator-visible dead letter.

Caller-owned idempotency keys are scoped by workspace, actor, command, and normalized
request. Exact retries return the original outcome; changed input is rejected. Replay
is privileged, workspace-scoped, audited, dry-runnable, and protected against duplicate
side effects. External effects require provider idempotency or preconditions plus
verification and reconciliation.

## 15. Architecture fitness-test contract

Continuous integration enforces:

- dependency direction and provider SDK confinement;
- tenant non-null/composite keys and forced RLS;
- typed workspace/actor context;
- authorization before repository/provider mutation;
- atomic state/audit/outbox behavior;
- event compatibility and inbox idempotency;
- provider contracts;
- entity/projection integrity;
- derivative deletion;
- cross-workspace attacks;
- migration compatibility and recovery.

Each rule has a stable ID and link to this specification. Exceptions require an ADR or
expiring risk acceptance. Required checks cannot be disabled to merge.

## 16. Migration and recovery targets

The Phase 1 rehearsal uses a sanitized production-like snapshot and validates counts,
hashes, ownership, orphan detection, default organization/workspace mapping, credential
re-encryption, Gmail/Calendar/Drive shadow-read parity, resumable failures, dual-write
divergence, recovery decisions, and provider reconciliation. No live cutover occurs in
H0.

Initial design targets are:

| Measure | Target |
|---|---|
| API availability | 99.9% monthly for authenticated core APIs |
| API latency | 95% of ordinary reads under 500 ms, excluding external latency |
| Tenant isolation | Zero tolerated cross-workspace disclosure or mutation |
| Authorization revocation | Effective for new transactions within 60 seconds |
| Audit/outbox durability | Atomic with every material committed mutation |
| Recovery point objective | 15 minutes for PostgreSQL |
| Recovery time objective | 4 hours for core read/write service |
| Provider sync freshness | 95% within 15 minutes when the provider is healthy |
| Deletion verification | 95% within 24 hours; exceptions explicitly reported |

H0 proves design feasibility. H1 instruments these targets. Revision requires
operational evidence and an ADR.

## 17. H0 approval and exit evidence

H0 validation may begin when this specification and its superseding ADRs are accepted,
each P0 item has an assigned evidence requirement, and target documents have no
conflicting definition. The evidence itself is required to exit H0.

| P0 | Specification | Required evidence | Status |
|---|---|---|---|
| P0.1 | Section 2 | PostgreSQL key/RLS/pool prototype and attack tests | Pending H0 |
| P0.2 | Section 3 | Ownership state-machine review and invariant tests | Pending H0 |
| P0.3 | Section 4 | Session/revocation prototype and lifecycle matrix | Pending H0 |
| P0.4 | Section 5 | Policy prototype and authorization matrix | Pending H0 |
| P0.5 | Section 6 | Threat review with no unaccepted critical risk | Pending H0 |
| P0.6 | Section 7 | KMS rotation prototype and failure tests | Pending H0 |
| P0.7 | Section 8 | Custody prototype and quarantine/deletion tests | Pending H0 |
| P0.8 | Section 9 | Google/mock-provider conflict tests | Pending H0 |
| P0.9 | Section 10 | Derivative deletion simulation | Pending H0 |
| P0.10 | Section 11 | AI egress/red-team test-plan review | Pending H0 |
| P0.11 | Section 12 | Entity/projection prototype and integrity tests | Pending H0 |
| P0.12 | Section 13 | Dependency/scope fitness test | Pending H0 |
| P0.13 | Section 14 | Event/replay prototype and failure tests | Pending H0 |
| P0.14 | Section 15 | Executable CI fitness-test harness | Pending H0 |

H0 passes only when every status is `Accepted`, evidence is linked, and no critical
threat remains unaccepted. The Architecture Index then authorizes H1 production work.

## 18. Pull-request sequence

The first H0 validation pull request is:

> **H0-01: Add the architecture fitness-test harness and tenancy isolation prototype**

It contains no production feature. It establishes dependency rules, a disposable
PostgreSQL schema with composite tenant keys and forced RLS, transaction-local
workspace context, pool-reuse attack tests, and P0.1/P0.14 evidence links.

The first production pull request after H0 passes is:

> **H1-01: Add organization and workspace schema expansion**

It is additive and introduces organizations, workspaces, placement metadata, and
default Phase 1 ownership records behind unused paths. It includes composite tenant
keys, forced RLS, migration compatibility tests, audit/outbox integration, and no
user-facing behavior change.
