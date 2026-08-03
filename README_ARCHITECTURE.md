# Atlas Master Architecture Index

The single entry point to the Atlas architecture documentation.

**Owner:** Atlas Architecture Council  
**Current phase:** H3 — System Intelligence Layer
**Status:** Formal H0, H1, and H2 Exits accepted; H3 architecture approved through
PR #24; sequential H3 production implementation authorized by explicit slice approval
**Last updated:** August 2, 2026

## Core principle

Atlas is a provider-agnostic business operating system for multiple logically isolated
workspaces.

Google Workspace is the first fully operational provider, but it is not part of the
Atlas business model. Gmail, Google Calendar, and Google Drive must remain adapters
behind stable Atlas Core contracts.

The primary architecture invariant is:

> Every business object, connection, document, memory, search record, domain event,
> and audit event belongs to exactly one workspace. Every operation is authorized
> within that workspace context before data or an external provider is accessed.

## Platform status

### Phase 1 — complete

The Google Workspace Foundation is implemented and validated end to end:

- Gmail;
- Google Calendar;
- Google Drive;
- OAuth 2.0 and PKCE;
- incremental authorization;
- PostgreSQL;
- FastAPI;
- Docker;
- Alembic migrations;
- automated tests;
- live end-to-end validation.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for the detailed implementation status.

### H0–H2 — formally accepted and merged

The architecture phase, Formal H0 Exit, and Formal H1 Exit are complete. H1-01
through H1-10 are accepted and merged.

All P0 contracts and superseding ADRs are approved, P0.1–P0.14 evidence is accepted,
and the merge-blocking H0 Required Gate protects `master`. The accepted evidence and
workflow run are recorded in
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#17-h0-approval-and-exit-evidence).

The accepted H1 baseline includes organizations and workspaces, canonical identity,
revocable sessions, memberships and fixed roles, deterministic authorization,
execution context and forced RLS, managed envelope encryption, immutable audit and
transactional messaging, recovery and closure controls, and the synthetic-tenant
vertical-slice evidence. See
[H1_FORMAL_EXIT_REPORT.md](H1_FORMAL_EXIT_REPORT.md) and
[PROJECT_STATUS.md](PROJECT_STATUS.md).

The accepted H2 production decomposition is defined in
[H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md). H2-01 through H2-10 are accepted and
merged. The accepted decision and evidence are recorded in
[H2_EXIT_REPORT.md](H2_EXIT_REPORT.md).

### H3 — architecture approved; implementation gate open

The approved final reusable platform layer is defined by
[H3_ARCHITECTURE.md](H3_ARCHITECTURE.md), with stage-specific engineering gates in
[H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md) and the meaning of Atlas
Platform Complete in [H3_EXIT_DEFINITION.md](H3_EXIT_DEFINITION.md). Accepted ADR-033
consolidates the former H3–H8 delivery packaging into eleven sequential H3 slices.
PR #24 is the formal architecture acceptance. H3 production implementation is
authorized only one explicitly requested slice at a time; no business agent or H4 work
is authorized.

## Recommended reading order

### 1. [MISSION.md](MISSION.md)

Explains:

- why Atlas exists;
- which problems it solves;
- whom it serves;
- which principles it must never violate.

Start with the Mission so that technical decisions are evaluated against product
purpose rather than in isolation.

### 2. [VISION.md](VISION.md)

Describes:

- what Atlas should become over the next 5–10 years;
- strategic horizons;
- the intended user experience;
- non-goals;
- long-term success criteria.

### 3. [PROJECT_STATUS.md](PROJECT_STATUS.md)

Records the current Phase 1 state:

- implemented integrations;
- current architecture;
- PostgreSQL schema;
- API endpoints;
- test coverage;
- known limitations;
- technical debt in the existing implementation.

This document describes the system as it exists, not the target architecture.

### 4. [ARCHITECTURE.md](ARCHITECTURE.md)

Defines the target technical architecture:

- workspace-first modular monolith;
- bounded contexts;
- Identity and Access;
- organizations and workspaces;
- universal entity registry;
- typed domain projections;
- provider abstraction;
- event bus and transactional outbox;
- background jobs;
- search and embeddings;
- agent architecture;
- approvals;
- security;
- scalability;
- migration from Phase 1.

### 5. [DOMAIN_MODEL.md](DOMAIN_MODEL.md)

Defines the Atlas business model:

- organizations, workspaces, users, and memberships;
- universal entities and relationships;
- contacts, companies, projects, and tasks;
- communications, meetings, and calendar events;
- documents and files;
- assets, finance, shipments, and ideas;
- operational data;
- source documents;
- knowledge;
- memory;
- timeline;
- audit;
- recommendations;
- workflows and approvals.

The essential rule is:

> A universal entity provides shared identity and relationships, but never replaces
> typed operational aggregates.

Atlas must not become a universal EAV or JSON business model.

### 6. [DECISIONS.md](DECISIONS.md)

Contains the Architecture Decision Records:

- accepted architecture decisions;
- their rationale;
- their consequences;
- decisions that require revision following the CTO review.

ADRs preserve decision history. A change in direction does not delete an earlier
decision; a new ADR supersedes it.

### 7. [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md)

Provides an independent, critical CTO review of the target architecture.

The review deliberately attempts to break the design and covers:

- strengths;
- weaknesses;
- critical risks;
- hidden complexity;
- security and workspace-isolation risks;
- provider-abstraction problems;
- AI, memory, event bus, and audit risks;
- over-engineered and under-designed areas;
- ADR criticism;
- priority matrix;
- final CTO recommendation.

Architecture documents must not be used without considering this review.

### 8. [ARCHITECTURE_HARDENING.md](ARCHITECTURE_HARDENING.md)

Defines the mandatory work plan before Phase 2 implementation.

It converts the CTO review into 49 actionable issues:

- **P0:** 14 issues that must be resolved before implementation;
- **P1:** 16 issues that must be resolved during Phase 2;
- **P2:** 12 issues deferred until Phase 3;
- **P3:** 7 future considerations.

Each issue specifies:

- problem;
- risk;
- recommended solution;
- estimated effort;
- dependencies;
- impact on existing architecture documents.

The document concludes with the revised H0–H8 Phase 2 sequence.

### 9. [ROADMAP.md](ROADMAP.md)

Defines the long-term delivery sequence:

- tenancy and security foundation;
- provider-neutral connections;
- universal entity core;
- documents, timeline, knowledge, and memory;
- search;
- business modules;
- AI assistance;
- governed agents;
- provider ecosystem;
- platform scale.

Until hardening is complete, the roadmap is strategic direction rather than
implementation authorization.

### 10. [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)

Provides the normative engineering contract that translates approved architecture
into implementation rules:

- engineering principles;
- mandatory H0–H8 stage gates;
- Definition of Ready and Definition of Done;
- coding and migration standards;
- approval rules;
- testing, pull-request, and rollback or forward-fix requirements.

This guide does not define new architecture. When implementation conflicts with
architecture, implementation stops, the architecture is reviewed, and a superseding
ADR is approved when required.

### 11. [H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md)

Owns the implementable P0 contracts for tenancy, organization ownership, identity,
authorization, threat modeling, encryption, object custody, retention, AI egress,
provider conflicts, entity integrity, canonical scope, events, fitness tests,
migration rehearsal, recovery targets, and H0 acceptance evidence.

This specification authorizes H0 validation work. Its evidence matrix is the source of
truth for H0 exit status.

### 12. [H1_PLATFORM_SPEC.md](H1_PLATFORM_SPEC.md)

Defines the proposed canonical H1 production slice decomposition:

- mandatory H1 boundaries and cross-slice constraints;
- H1-01 completion context;
- H1-02 through H1-10 objectives, dependencies, acceptance criteria, and exclusions;
- the integrated Formal H1 Exit slice.

This specification is accepted. Each production slice still requires explicit
authorization and predecessor acceptance.

### 13. [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md)

Defines the accepted H2 Phase 1 migration decomposition:

- canonical connections, managed credentials, and OAuth transactions;
- provider mirrors and neutral capability contracts;
- reversible Gmail, Calendar, and Drive adapter migration;
- cutover stabilization and Formal H2 Exit.

This specification is accepted and formally closed. H2-01 through H2-10 are accepted
and merged.

### 14. H3 blueprint

[H3_ARCHITECTURE.md](H3_ARCHITECTURE.md) defines the approved System Intelligence
Layer and H3-01 through H3-11 slice architecture.

[H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md) defines H3-specific delivery,
compatibility, migration, test, and evidence rules while inheriting the repository-wide
contract from `IMPLEMENTATION_GUIDE.md`.

[H3_EXIT_DEFINITION.md](H3_EXIT_DEFINITION.md) exclusively defines the Formal H3 Exit
and the phrase “Atlas Platform Complete.”

## Architecture document hierarchy

When documents conflict, apply the following precedence:

1. Security, tenancy, and legal invariants.
2. Approved superseding ADRs.
3. `H0_FOUNDATION_SPEC.md`.
4. Accepted stage platform specifications.
5. `ARCHITECTURE_HARDENING.md`.
6. `ARCHITECTURE_REVIEW.md`.
7. `ARCHITECTURE.md`.
8. `DOMAIN_MODEL.md`.
9. `ROADMAP.md`.
10. `VISION.md` and `MISSION.md` as strategic context.
11. `PROJECT_STATUS.md` as a description of the current implementation.

The review has precedence over the original architecture because an identified risk
cannot be ignored merely because an earlier ADR is marked Accepted.

## Document and concept ownership

Every architecture or engineering artifact has one accountable owner and one
non-overlapping canonical responsibility.

| Document | Accountable owner | Canonical responsibility |
|---|---|---|
| `README_ARCHITECTURE.md` | Atlas Architecture Council | Navigation, ownership registry, precedence, and current architecture-stage status |
| `README.md` | Atlas Platform Engineering | Repository onboarding and developer entry points |
| `MISSION.md` | Atlas Executive Leadership | Product purpose and enduring mission |
| `VISION.md` | Atlas Executive Leadership | Five-to-ten-year product direction and non-goals |
| `PROJECT_STATUS.md` | Atlas Platform Engineering | Verified current implementation state |
| `ARCHITECTURE.md` | Atlas Architecture Council | Target system shape, bounded contexts, and dependency boundaries |
| `DOMAIN_MODEL.md` | Atlas Domain Council | Canonical business terminology, entities, aggregates, and state distinctions |
| `DECISIONS.md` | Atlas Architecture Council | Architecture decision history and supersession |
| `ARCHITECTURE_REVIEW.md` | Atlas CTO | Historical critical review and identified risks |
| `ARCHITECTURE_HARDENING.md` | Atlas Architecture Council | Priority classification and canonical H0–H8 purpose and sequence |
| `ROADMAP.md` | Atlas Product and Engineering Leadership | Strategic phase outcomes beyond the H0–H8 implementation sequence |
| `IMPLEMENTATION_GUIDE.md` | Atlas Engineering | Engineering rules, readiness, completion, stage execution gates, tests, migrations, approvals, and pull-request contract |
| `H0_FOUNDATION_SPEC.md` | Atlas Core | Implementable P0 contracts, threat register, targets, and H0 evidence status |
| `H1_PLATFORM_SPEC.md` | Atlas Core | H1 slice sequence, slice objectives, boundaries, dependencies, and acceptance criteria |
| `H2_PLATFORM_SPEC.md` | Atlas Core | H2 slice sequence, slice objectives, boundaries, dependencies, acceptance criteria, and evidence contract |
| `H3_ARCHITECTURE.md` | Atlas Architecture Council | H3 vision, component boundaries, slice sequence, dependencies, and acceptance criteria |
| `H3_IMPLEMENTATION_GUIDE.md` | Atlas Platform Engineering | H3-specific implementation order, constraints, compatibility, migrations, testing, and evidence gates |
| `H3_EXIT_DEFINITION.md` | Atlas Architecture Council | Formal H3 Exit and the definition of Atlas Platform Complete |

A document may summarize another document only for navigation or context and must link
to the canonical owner. Summaries are non-normative and must not restate detailed
requirements, decision rules, enumerations, or acceptance criteria.

### Concept ownership rules

- Architecture decisions exist only in `DECISIONS.md`.
- Domain definitions exist only in `DOMAIN_MODEL.md`.
- P0 implementation contracts exist only in `H0_FOUNDATION_SPEC.md`.
- H0–H8 purpose and ordering exist only in `ARCHITECTURE_HARDENING.md`.
- H0–H8 engineering prerequisites, deliverables, tests, and exit criteria exist only in
  `IMPLEMENTATION_GUIDE.md`.
- H1 slice-level decomposition exists only in `H1_PLATFORM_SPEC.md`.
- H2 slice-level decomposition exists only in `H2_PLATFORM_SPEC.md`.
- H3 component and slice architecture exists only in `H3_ARCHITECTURE.md`.
- H3-specific implementation rules exist only in `H3_IMPLEMENTATION_GUIDE.md`.
- Formal H3 Exit and Atlas Platform Complete exist only in `H3_EXIT_DEFINITION.md`.
- Strategic phase outcomes exist only in `ROADMAP.md`.
- Engineering workflow and quality rules exist only in `IMPLEMENTATION_GUIDE.md`.
- Current implementation claims exist only in `PROJECT_STATUS.md`.

## P0 decision registry

P0 architecture blockers are resolved by ADR-021 through ADR-032 in
[DECISIONS.md](DECISIONS.md#h0-superseding-decisions). Earlier ADRs remain as historical
records and are superseded or constrained as stated by those decisions.

### ADR inbound-reference registry

This navigation registry provides an explicit inbound reference for every ADR. The ADR
text and status remain canonical only in `DECISIONS.md`.

| ADRs | Governing area |
|---|---|
| [ADR-001](DECISIONS.md#adr-001-use-a-workspace-first-tenancy-model), [ADR-021](DECISIONS.md#adr-021-require-organization-ownership-for-every-workspace) | Workspace and organization ownership |
| [ADR-002](DECISIONS.md#adr-002-build-a-modular-monolith-before-microservices) | Deployment shape |
| [ADR-003](DECISIONS.md#adr-003-universal-entity-registry-with-typed-projections), [ADR-028](DECISIONS.md#adr-028-constrain-universal-entities-and-the-phase-2-core) | Universal entity and canonical scope |
| [ADR-004](DECISIONS.md#adr-004-provider-apis-are-adapters-not-the-business-model), [ADR-026](DECISIONS.md#adr-026-separate-provider-capability-and-synchronization-contracts) | Provider abstraction and synchronization |
| [ADR-005](DECISIONS.md#adr-005-separate-operational-data-documents-knowledge-memory-timeline-and-audit), [ADR-027](DECISIONS.md#adr-027-govern-object-custody-and-derivative-lineage) | Data planes, custody, and lineage |
| [ADR-006](DECISIONS.md#adr-006-use-postgresql-as-the-initial-system-of-record-and-search-platform), [ADR-032](DECISIONS.md#adr-032-retain-postgresql-until-extraction-criteria-are-measured) | PostgreSQL and extraction thresholds |
| [ADR-007](DECISIONS.md#adr-007-use-current-state-persistence-plus-events-not-universal-event-sourcing) | Persistence model |
| [ADR-008](DECISIONS.md#adr-008-use-a-transactional-outbox-and-at-least-once-delivery), [ADR-029](DECISIONS.md#adr-029-specify-ordered-at-least-once-events-and-command-concurrency) | Events and concurrency |
| [ADR-009](DECISIONS.md#adr-009-rbac-plus-contextual-policy-deny-by-default), [ADR-024](DECISIONS.md#adr-024-centralize-deterministic-authorization-at-application-boundaries) | Authorization |
| [ADR-010](DECISIONS.md#adr-010-agents-use-the-same-application-commands-as-humans) | Agent command boundary |
| [ADR-011](DECISIONS.md#adr-011-approval-binds-to-an-immutable-action-digest) | Approval binding |
| [ADR-012](DECISIONS.md#adr-012-hybrid-permission-aware-retrieval) | Retrieval |
| [ADR-013](DECISIONS.md#adr-013-managed-envelope-encryption-for-provider-credentials), [ADR-025](DECISIONS.md#adr-025-make-managed-per-record-envelope-encryption-a-prerequisite) | Credential encryption |
| [ADR-014](DECISIONS.md#adr-014-shared-schema-row-tenancy-first), [ADR-022](DECISIONS.md#adr-022-use-cell-ready-composite-key-tenancy) | Tenant database isolation |
| [ADR-015](DECISIONS.md#adr-015-documents-are-immutable-versions-files-are-provider-placements) | Documents and files |
| [ADR-016](DECISIONS.md#adr-016-finance-uses-typed-aggregates-and-ledger-rules) | Finance boundary |
| [ADR-017](DECISIONS.md#adr-017-timeline-and-audit-are-separate) | Timeline and audit |
| [ADR-018](DECISIONS.md#adr-018-no-cross-workspace-reasoning-by-default) | Cross-workspace reasoning |
| [ADR-019](DECISIONS.md#adr-019-durable-jobs-for-asynchronous-work) | Durable jobs |
| [ADR-020](DECISIONS.md#adr-020-evolve-through-expand-and-contract-migrations) | Migration strategy |
| [ADR-023](DECISIONS.md#adr-023-use-canonical-identities-and-revocable-server-side-sessions) | Identity and sessions |
| [ADR-030](DECISIONS.md#adr-030-treat-untrusted-content-as-data-and-govern-ai-egress) | AI security and egress |
| [ADR-031](DECISIONS.md#adr-031-enforce-architecture-invariants-with-fitness-tests) | Architecture fitness tests |
| [ADR-033](DECISIONS.md#adr-033-consolidate-the-remaining-reusable-platform-foundation-into-h3) | H3 final-platform sequencing and post-H3 business-agent boundary |

## P0 Architecture Gate

The **H0 entry and exit gates are satisfied**. The P0 contracts, threat register,
initial targets, scope constraints, superseding ADRs, executable evidence, CI fitness
gate, and branch protection are accepted. Production H1 work is authorized in the
canonical sequence.

P0 priority, problem, risk, dependency, and effort classification is owned by
[ARCHITECTURE_HARDENING.md](ARCHITECTURE_HARDENING.md#p0--must-fix-before-implementation).
Approved P0 contracts and executable evidence status are owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#17-h0-approval-and-exit-evidence).

## Revised Phase 2 sequence

The canonical H0–H8 purpose and ordering are defined only in
[ARCHITECTURE_HARDENING.md](ARCHITECTURE_HARDENING.md#revised-phase-2-implementation-sequence).
Engineering gates are defined only in
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#3-canonical-implementation-order).

## Architecture Hardening deliverables

The canonical deliverable list is owned by
[ARCHITECTURE_HARDENING.md](ARCHITECTURE_HARDENING.md#hardening-stage-deliverables).
Current acceptance status is owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#17-h0-approval-and-exit-evidence).

## Architecture governance rules

### Changing architecture

Every fundamental change must:

1. describe the problem and context;
2. list the alternatives considered;
3. record the decision and consequences;
4. include a migration and rollback strategy;
5. add or update an ADR;
6. update every affected document;
7. add an architecture fitness test when the invariant can be verified automatically.

### Engineering implementation contract

The normative Definition of Ready, Definition of Done, coding standards, migration
rules, approval rules, and pull-request contract are defined only in
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md).

The Architecture Index remains the navigation layer and does not duplicate these
engineering rules.

## Prohibited approaches

Prohibited and deferred architecture approaches are owned by accepted ADRs and the
scope/non-goals in
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#1-h0-scope-and-non-goals). Engineering
enforcement is owned by `IMPLEMENTATION_GUIDE.md`.

## Related documents

| Document | Role |
|---|---|
| [MISSION.md](MISSION.md) | Why Atlas exists |
| [VISION.md](VISION.md) | Where Atlas is going |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | What is implemented now |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Target technical system |
| [DOMAIN_MODEL.md](DOMAIN_MODEL.md) | Business and data model |
| [DECISIONS.md](DECISIONS.md) | Architecture decision history |
| [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md) | Critical CTO review |
| [ARCHITECTURE_HARDENING.md](ARCHITECTURE_HARDENING.md) | Mandatory hardening plan |
| [ROADMAP.md](ROADMAP.md) | Delivery sequence |
| [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) | Normative engineering contract |
| [H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md) | Normative P0 contracts and H0 evidence |
| [H1_PLATFORM_SPEC.md](H1_PLATFORM_SPEC.md) | Accepted H1 slice decomposition |
| [H1_FORMAL_EXIT_REPORT.md](H1_FORMAL_EXIT_REPORT.md) | Formal H1 acceptance decision and evidence |
| [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md) | Accepted H2 slice decomposition |
| [H2_01_ACCEPTANCE_EVIDENCE.md](H2_01_ACCEPTANCE_EVIDENCE.md) | H2-01 implementation and verification evidence |
| [H2_02_ACCEPTANCE_EVIDENCE.md](H2_02_ACCEPTANCE_EVIDENCE.md) | H2-02 implementation and verification evidence |
| [H2_02_CREDENTIAL_OPERATIONS.md](H2_02_CREDENTIAL_OPERATIONS.md) | H2-02 credential migration, failure, and rollback runbook |
| [H2_03_ACCEPTANCE_EVIDENCE.md](H2_03_ACCEPTANCE_EVIDENCE.md) | H2-03 implementation and verification evidence |
| [H2_04_ACCEPTANCE_EVIDENCE.md](H2_04_ACCEPTANCE_EVIDENCE.md) | H2-04 implementation and verification evidence |
| [H2_05_ACCEPTANCE_EVIDENCE.md](H2_05_ACCEPTANCE_EVIDENCE.md) | H2-05 implementation and verification evidence |
| [H2_06_ACCEPTANCE_EVIDENCE.md](H2_06_ACCEPTANCE_EVIDENCE.md) | H2-06 implementation and verification evidence |
| [H2_07_ACCEPTANCE_EVIDENCE.md](H2_07_ACCEPTANCE_EVIDENCE.md) | H2-07 implementation and verification evidence |
| [H2_08_ACCEPTANCE_EVIDENCE.md](H2_08_ACCEPTANCE_EVIDENCE.md) | H2-08 implementation and verification evidence |
| [H2_09_ACCEPTANCE_EVIDENCE.md](H2_09_ACCEPTANCE_EVIDENCE.md) | H2-09 implementation and verification evidence |
| [H2_09_CUTOVER_OPERATIONS.md](H2_09_CUTOVER_OPERATIONS.md) | H2-09 cutover, rollback, and compatibility inventory runbook |
| [H2_10_ACCEPTANCE_EVIDENCE.md](H2_10_ACCEPTANCE_EVIDENCE.md) | H2-10 integrated conformance and verification evidence |
| [H2_EVIDENCE_MATRIX.md](H2_EVIDENCE_MATRIX.md) | Complete H2 criterion-to-evidence trace |
| [H2_SECURITY_REVIEW.md](H2_SECURITY_REVIEW.md) | Formal H2 threat and residual-risk review |
| [H2_EXIT_REPORT.md](H2_EXIT_REPORT.md) | Formal H2 Exit decision and completed baseline |
| [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md) | Approved H3 System Intelligence architecture and slice decomposition |
| [H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md) | Approved H3-specific engineering contract |
| [H3_EXIT_DEFINITION.md](H3_EXIT_DEFINITION.md) | Active Formal H3 Exit and Atlas Platform Complete definition |
| [H3_01_ACCEPTANCE_EVIDENCE.md](H3_01_ACCEPTANCE_EVIDENCE.md) | H3-01 Resource Graph implementation and verification evidence |
| [H3_02_ACCEPTANCE_EVIDENCE.md](H3_02_ACCEPTANCE_EVIDENCE.md) | H3-02 durable execution and scheduler implementation evidence |
| [H3_03_ACCEPTANCE_EVIDENCE.md](H3_03_ACCEPTANCE_EVIDENCE.md) | H3-03 document custody and governed derivation implementation evidence |
| [H3_04_ACCEPTANCE_EVIDENCE.md](H3_04_ACCEPTANCE_EVIDENCE.md) | H3-04 Knowledge Service and Timeline implementation evidence |
| [H3_05_ACCEPTANCE_EVIDENCE.md](H3_05_ACCEPTANCE_EVIDENCE.md) | H3-05 governed Memory Manager implementation evidence |
| [H3_06_ACCEPTANCE_EVIDENCE.md](H3_06_ACCEPTANCE_EVIDENCE.md) | H3-06 Search and Context Assembly implementation evidence |
| [H3_07_ACCEPTANCE_EVIDENCE.md](H3_07_ACCEPTANCE_EVIDENCE.md) | H3-07 Task Manager implementation and verification evidence |
| [H3_08_ACCEPTANCE_EVIDENCE.md](H3_08_ACCEPTANCE_EVIDENCE.md) | H3-08 Workflow and Approval Engine implementation and verification evidence |
| [H3_09_ACCEPTANCE_EVIDENCE.md](H3_09_ACCEPTANCE_EVIDENCE.md) | H3-09 Notification Center implementation and verification evidence |
| [H3_10_ACCEPTANCE_EVIDENCE.md](H3_10_ACCEPTANCE_EVIDENCE.md) | H3-10 Agent Platform Contracts implementation and verification evidence |

## Next action

H3-01 is Accepted and merged through PR #26 at `a4602b6`. H3-02 is Accepted and
merged through PR #28 at `915386c`. H3-03 is Accepted and merged through PR #30 at
`3be4480`. H3-04 is Accepted and merged through PR #32 at `38c326d`. H3-05 is
Accepted and merged through PR #34 at `670205d`. H3-06 is Accepted and merged through
PR #36 at `a34322e`. H3-07 is Accepted and merged through PR #38 at `c26b35d`. H3-08
is Accepted and merged through PR #40 at `386d365`. H3-09 is Accepted and merged
through PR #42 at `e4ae56b`; accepted production migration head is
`0030_h3_notification_center`.

H3-09 is formally Accepted. The H3-10 Agent Platform Contracts security,
authorization, classification, custody, retention, deletion, recovery, model/tool,
approval, budget, evaluation, and migration impacts are approved in
[H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md#161-h3-10-accepted-security-review-scope).
The H3-10 implementation gate is explicitly open for one dedicated slice after this
governance synchronization is merged into `origin/master`. H3-11, H4,
provider-specific integrations, connectors, business agents, external integrations,
and UI functionality remain unauthorized.
