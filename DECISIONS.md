# Atlas Architecture Decisions

**Owner:** Atlas Architecture Council

This file contains the foundational Architecture Decision Records (ADRs). Each ADR is
`Accepted` unless stated otherwise. Future changes should append a superseding ADR
rather than rewriting historical rationale.

## ADR-001: Use a workspace-first tenancy model

**Status:** Accepted

**Decision:** Workspace is the mandatory ownership and isolation boundary for all
tenant data, connections, memory, search, events, and agents. Organization is an
optional administrative parent. Users participate through memberships.

**Why:** User-owned data cannot represent teams, multiple businesses, or shared
provider accounts safely.

**Consequences:** Every tenant query and uniqueness constraint includes workspace.
Migration from Phase 1 requires backfill and isolation testing.

## ADR-002: Build a modular monolith before microservices

**Status:** Accepted

**Decision:** Keep one primary deployable application and PostgreSQL database while
enforcing bounded contexts, ports, commands, and events.

**Why:** Domain boundaries are still evolving. Microservices would increase distributed
failure modes without creating product value.

**Consequences:** Module ownership and dependency rules must be enforced. Modules can be
extracted later based on measured need.

## ADR-003: Universal entity registry with typed projections

**Status:** Accepted

**Decision:** All connectable objects receive an entity identity, but operational data
lives in typed domain tables/aggregates.

**Why:** A universal EAV/JSON model sacrifices constraints and maintainability; isolated
typed domains prevent generic relationships and features.

**Consequences:** Creating a typed object also creates an entity registry row. Generic
capabilities reference the entity ID.

## ADR-004: Provider APIs are adapters, not the business model

**Status:** Accepted

**Decision:** Business/application code depends on capability ports and canonical DTOs.
Google, Microsoft, IMAP, Dropbox, and future systems are adapters.

**Why:** Provider payloads and semantics change and must be replaceable.

**Consequences:** Some provider features require explicit capability/extension handling.
Adapters require contract tests.

## ADR-005: Separate operational data, documents, knowledge, memory, timeline, and audit

**Status:** Accepted

**Decision:** These planes use distinct models and authority rules.

**Why:** Treating an AI extraction, source document, operational record, and historical
event as the same object creates correctness and governance failures.

**Consequences:** Promotion between planes is explicit and provenance is retained.

## ADR-006: Use PostgreSQL as the initial system of record and search platform

**Status:** Accepted

**Decision:** Use PostgreSQL for relational data, JSON extensions, full-text search,
pgvector, outbox, and initial durable job state.

**Why:** It provides strong transactions and sufficient capability while minimizing
operational systems.

**Consequences:** Embeddings must migrate from JSONB/Python cosine search to pgvector.
External search or brokers require measured justification.

## ADR-007: Use current-state persistence plus events, not universal event sourcing

**Status:** Accepted

**Decision:** Store authoritative current state in typed tables and append domain/audit
events. Use event sourcing only for a domain with demonstrated need.

**Why:** Universal event sourcing adds projection, migration, debugging, and operational
complexity.

**Consequences:** Timeline is a projection; audit is immutable; operational tables
remain directly queryable.

## ADR-008: Use a transactional outbox and at-least-once delivery

**Status:** Accepted

**Decision:** Commands write state, audit, and outbox records atomically. Consumers are
idempotent and track processed events.

**Why:** Dual-writing the database and a broker is unsafe. Exactly-once delivery is not
a realistic system-wide assumption.

**Consequences:** Event schemas are versioned; idempotency and replay are first-class.

## ADR-009: RBAC plus contextual policy, deny by default

**Status:** Accepted

**Decision:** Roles grant stable permissions; policies constrain them by workspace,
resource, sensitivity, value, state, and actor context.

**Why:** Pure RBAC becomes role explosion; unrestricted ABAC becomes difficult to
explain and administer.

**Consequences:** Authorization decisions are centralized, testable, and auditable.

## ADR-010: Agents use the same application commands as humans

**Status:** Accepted

**Decision:** Agents receive delegated actor context and can invoke only registered
tools mapped to authorized commands/queries.

**Why:** Direct database/provider access would bypass validation, approval, and audit.

**Consequences:** Tools declare permissions, risk, side effects, reversibility, and
verification.

## ADR-011: Approval binds to an immutable action digest

**Status:** Accepted

**Decision:** Approval covers exact normalized action inputs and relevant context.
Material changes invalidate approval.

**Why:** Approving a vague intent must not authorize a later, altered action.

**Consequences:** Workflows may pause and re-request approval after replanning.

## ADR-012: Hybrid, permission-aware retrieval

**Status:** Accepted

**Decision:** Combine structured filters, full text, vectors, graph context, authority,
and freshness. Apply workspace/visibility filters before returning content.

**Why:** Vector search alone is not reliable for exact identifiers, recency, authority,
or authorization.

**Consequences:** Search documents and embeddings are versioned and carry visibility.

## ADR-013: Managed envelope encryption for provider credentials

**Status:** Target; migration required

**Decision:** Replace the single environment Fernet key with envelope encryption backed
by managed KMS and key versions.

**Why:** Long-lived multi-tenant credentials require rotation, revocation, audit, and
blast-radius control.

**Consequences:** Existing credentials need online re-encryption and rotation tooling.

## ADR-014: Shared-schema row tenancy first

**Status:** Accepted

**Decision:** Use `workspace_id` row isolation plus application authorization and
PostgreSQL RLS defense in depth.

**Why:** Nine initial workspaces do not justify database-per-tenant complexity.

**Consequences:** Repository APIs require workspace context. Future placement can route
selected workspaces to dedicated databases.

## ADR-015: Documents are immutable versions; files are provider placements

**Status:** Accepted

**Decision:** A logical document owns immutable content versions. Provider files
represent placements/references and may change externally.

**Why:** Conflating Drive/OneDrive file identity with document identity prevents
provider migration and reliable history.

**Consequences:** Hashing, version lineage, extraction, and provider references are
separate concerns.

## ADR-016: Finance uses typed aggregates and ledger rules

**Status:** Accepted

**Decision:** Invoices, payments, transactions, amounts, and ledgers use explicit
schemas, decimal money, currency, immutable postings, and approval policy.

**Why:** Finance cannot safely live in generic entity attributes or AI-extracted facts.

**Consequences:** Extracted financial knowledge requires validation/promotion before it
becomes operational finance.

## ADR-017: Timeline and audit are separate

**Status:** Accepted

**Decision:** Timeline is a user-facing business projection; audit is an immutable
security/accountability record.

**Why:** Their audiences, retention, redaction, performance, and completeness differ.

**Consequences:** One domain event may produce both, but neither substitutes for the
other.

## ADR-018: No cross-workspace reasoning by default

**Status:** Accepted

**Decision:** Search, memory, agents, and recommendations operate within one workspace
unless an explicit, authorized sharing grant supplies specific data.

**Why:** A user belonging to several workspaces does not imply data may be mixed.

**Consequences:** Personal and business knowledge remain isolated. Cross-workspace
features require explicit product and security design.

## ADR-019: Durable jobs for asynchronous work

**Status:** Accepted

**Decision:** Provider sync, extraction, indexing, recommendations, and workflows run as
durable jobs with retries, leases, idempotency, cancellation, and dead letters.

**Why:** In-process background tasks are lost on deploy/crash and cannot support
long-running workflows.

**Consequences:** Worker health, queue lag, and replay become operational concerns.

## ADR-020: Evolve through expand-and-contract migrations

**Status:** Accepted

**Decision:** Refactor Phase 1 incrementally using additive schema, backfill, dual
read/write where needed, verification, and later removal.

**Why:** A rewrite risks the working Google foundation and delays feedback.

**Consequences:** Temporary compatibility code is allowed only with an owner and removal
milestone.

# H0 superseding decisions

These decisions resolve the P0 architecture blockers. Earlier ADRs remain as historical
records.

## ADR-021: Require organization ownership for every workspace

**Status:** Accepted; supersedes the optional-organization part of ADR-001

**Decision:** Every workspace belongs to exactly one business or personal organization.
Organization administration does not imply workspace-content access. Personal uses a
single-member personal organization.

**Why:** Legal ownership, billing, administration, retention, and lifecycle cannot
remain ambiguous.

**Consequences:** Workspace transfer is prohibited in Phase 2. Last-owner and closure
invariants are mandatory. See `H0_FOUNDATION_SPEC.md` sections 2–3.

## ADR-022: Use cell-ready composite-key tenancy

**Status:** Accepted; supersedes ADR-014

**Decision:** Shared-schema PostgreSQL remains the first deployment model, but every
tenant relation uses workspace-inclusive candidate and foreign keys, forced RLS for
non-bypass runtime roles, transaction-local tenant context, and explicit placement.

**Why:** Application predicates and global IDs do not prevent cross-workspace joins,
pool-context leaks, or future placement migration.

**Consequences:** Tenant context is mandatory in repositories, commands, events, and
jobs. H0 must prove it with PostgreSQL adversarial tests. See
`H0_FOUNDATION_SPEC.md` section 2.

## ADR-023: Use canonical identities and revocable server-side sessions

**Status:** Accepted

**Decision:** Authenticate through OIDC Authorization Code Flow with PKCE and use
opaque, hashed, server-side sessions. External identities link by issuer/subject;
verified email never causes automatic account merging.

**Why:** Atlas requires immediate revocation, safe recovery, identity provenance, and
strong-authentication enforcement.

**Consequences:** Invitations, recovery, MFA, service principals, and support identities
follow `H0_FOUNDATION_SPEC.md` section 4.

## ADR-024: Centralize deterministic authorization at application boundaries

**Status:** Accepted; supersedes ADR-009

**Decision:** Use fixed role templates plus contextual constraints with explicit
deny-first precedence. Every command and query receives a versioned policy decision
before repository or provider access. Custom roles and groups are deferred.

**Why:** A general RBAC-plus-ABAC statement is not implementable or consistently
testable.

**Consequences:** Decisions return reason codes and obligations. Revocation applies to
new transactions, and approval never creates permission. See
`H0_FOUNDATION_SPEC.md` section 5.

## ADR-025: Make managed per-record envelope encryption a prerequisite

**Status:** Accepted; supersedes the deferred status of ADR-013

**Decision:** Provider credentials require per-record authenticated encryption with a
DEK wrapped by a managed, versioned KMS KEK and tenant-bound encryption context.

**Why:** A single application key has unacceptable blast radius and cannot support safe
rotation or revocation.

**Consequences:** Phase 1 credentials require verified online re-encryption. H0 proves
rotation and failure behavior. See `H0_FOUNDATION_SPEC.md` section 7.

## ADR-026: Separate provider capability and synchronization contracts

**Status:** Accepted; supersedes the synchronization scope of ADR-004

**Decision:** Capability ports define provider-neutral business operations.
Synchronization contracts separately define mirrors, authority, versions, tombstones,
conflicts, reconciliation, and outbound preconditions.

**Why:** Capability interfaces cannot decide data authority or concurrent external
changes safely.

**Consequences:** Adapters require capability conformance and synchronization conflict
tests. See `H0_FOUNDATION_SPEC.md` section 9.

## ADR-027: Govern object custody and derivative lineage

**Status:** Accepted; extends ADR-005 and ADR-015

**Decision:** Immutable document versions use an S3-compatible object-storage port with
quarantine, verification, classification, and tenant placement. Every derivative
records source lineage and participates in policy-controlled deletion verification.

**Why:** Provider files are not durable evidence, PostgreSQL is not the ordinary blob
store, and deletion requires a complete derivative graph.

**Consequences:** Legal hold and minimum retention override erasure. Backups expire
under policy. See `H0_FOUNDATION_SPEC.md` sections 8 and 10.

## ADR-028: Constrain universal entities and the Phase 2 core

**Status:** Accepted; supersedes the unconstrained scope of ADR-003 and constrains ADR-016

**Decision:** Only approved connectable operational aggregates receive entity identity,
created transactionally with typed projections. Phase 2 core is limited to tenancy,
IAM, connections, core entities, communications/documents, activity/audit, search, and
governed memory. Finance and other vertical domains remain later modules.

**Why:** An unconstrained registry and speculative domains create integrity failures
and premature coupling.

**Consequences:** Arbitrary entity types, generalized knowledge graphs, and Phase 2
ledger implementation are prohibited. See `H0_FOUNDATION_SPEC.md` sections 12–13.

## ADR-029: Specify ordered at-least-once events and command concurrency

**Status:** Accepted; supersedes the incomplete contract in ADR-008

**Decision:** Commands use optimistic concurrency and caller-owned idempotency keys.
State, audit, and outbox commit atomically. Events carry workspace, aggregate sequence,
and schema version; consumers use inbox deduplication, gap handling, quarantine, and
authorized replay.

**Why:** At-least-once delivery without these semantics permits duplicate effects and
corrupt projections.

**Consequences:** Exact system-wide once-only delivery is not claimed. External effects
require provider idempotency or preconditions and verification. See
`H0_FOUNDATION_SPEC.md` section 14.

## ADR-030: Treat untrusted content as data and govern AI egress

**Status:** Accepted; extends ADR-010, ADR-011, ADR-012, and ADR-018

**Decision:** AI context is workspace-scoped, permission-filtered, minimized,
classification-routed, provenance-preserving, and separated from trusted instructions.
Model output acts only through registered commands with runtime policy validation.

**Why:** Permission-aware retrieval alone does not stop prompt injection, sensitive
data egress, or tool-instruction attacks.

**Consequences:** Unsupported classifications deny model routing. AI features require
red-team tests. See `H0_FOUNDATION_SPEC.md` section 11.

## ADR-031: Enforce architecture invariants with fitness tests

**Status:** Accepted

**Decision:** CI enforces module boundaries, provider isolation, tenant-key/RLS rules,
command authorization, audit/outbox atomicity, event compatibility, adapter contracts,
projection integrity, and deletion propagation.

**Why:** Prose-only invariants drift during implementation.

**Consequences:** Each rule has a stable ID. Exceptions require an ADR or expiring risk
acceptance. See `H0_FOUNDATION_SPEC.md` section 15.

## ADR-032: Retain PostgreSQL until extraction criteria are measured

**Status:** Accepted; narrows ADR-006 and defers final ADR-019 technology selection

**Decision:** PostgreSQL remains the initial system of record, search platform,
outbox/inbox, and H0 durable-state prototype. Extraction requires measured SLO, scale,
isolation, or team-ownership evidence.

**Why:** Premature infrastructure creates distributed failure modes before PostgreSQL
has been shown insufficient.

**Consequences:** H0 specifies job/event semantics but does not choose the permanent P1
job platform. See `H0_FOUNDATION_SPEC.md` sections 13–16.
