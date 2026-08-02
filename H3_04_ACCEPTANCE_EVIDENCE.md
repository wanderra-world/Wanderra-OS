# H3-04 Knowledge Service and Timeline Acceptance Evidence

**Owner:** Atlas Platform Engineering
**Status:** Accepted and merged through PR #32
**Governing specification:** [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md#h3-04-knowledge-service-and-timeline)
**Engineering contract:** [H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md#113-h3-04-accepted-security-review-scope)

## 1. Prerequisites

- H3-03 is Accepted and merged through PR #30 at `3be4480`.
- PR #31 opened the H3-04 gate and is merged into `origin/master` at `6392d11`.
- The complete H3 architecture, implementation guide, exit definition, Architecture
  Index, project status, H2 specification, base engineering contract, ADR registry,
  and H3-03 evidence were reread from the merged baseline.
- The user explicitly authorized H3-04 only.
- The approved H3-04 security, classification, custody, retention, deletion,
  recovery, migration, and rollback constraints were verified before branching.

## 2. Implemented scope

- Canonical typed claims with deterministic fact identity, typed canonical values,
  confidence, validity intervals, extraction version, classification, policy version,
  review state, optimistic state version, and immutable resource subject.
- Immutable H3-03 document-version and optional chunk source spans with hash custody.
- A separate derivation digest that makes equivalent replay idempotent and rejects
  changed source, span, extractor, or policy input for an existing fact identity.
- Explicit contradiction and supersession relations that preserve both claims.
- Deterministic timeline inputs, source-event deduplication, stable ordering,
  visibility, resource/claim links, rebuild removal, and versioned checkpoints.
- Durable, idempotent H3-02 source-disposition commands and persisted propagation
  state that invalidates dependent claims and removes dependent timeline entries.
- H1 authorization, canonical execution context, audit, transactional outbox,
  composite tenant keys, and forced RLS at every boundary.

## 3. Explicit exclusions

No HTTP API, provider logic, ontology editor, graph database, operational-data
mutation, memory, embeddings, search, recommendations, task/workflow/notification
behavior, planner, business agent, H3-05+, or H4 functionality is introduced.

## 4. Migration and rollback

- Revision: `0025_h3_knowledge_timeline`.
- Parent: accepted H3-03 revision `0024_h3_document_custody`.
- Six additive tenant tables: claims, evidence, relations, source dispositions,
  timeline entries, and timeline checkpoints.
- Every table has organization/workspace/cell identity, workspace-consistent foreign
  keys, closed-workspace write protection, and enabled and forced RLS before access.
- Empty upgrade, repeated upgrade, downgrade to H3-03, and re-upgrade pass.
- Populated downgrade fails closed with a reviewed-forward-fix/export instruction.
- Projection workers can stop and timeline state can rebuild without altering claims,
  source documents, operational data, or audit evidence.

## 5. Red → Green → Refactor evidence

Red began with missing `app.knowledge` contracts, models, service, repository, job
adapter, migration, and architecture boundary. Green introduced only the typed claim,
evidence, contradiction/supersession, timeline projection/checkpoint, and source
disposition capabilities required by H3-04 tests.

Refactor added derivation-input replay protection after reviewing same-fact evidence
substitution, persisted review evidence, durable disposition state, timeline
reactivation during rebuild, and atomic disposition audit/outbox evidence while the
focused suite remained green.

## 6. Verification evidence

| Verification | Result |
|---|---|
| New H3-04 tests | 15 tests across contracts, PostgreSQL, migration, RLS, replay, timeline rebuild, deletion lineage, and architecture boundaries |
| Complete local regression suite | 541 passed against PostgreSQL 16; one pre-existing Starlette/httpx deprecation warning |
| H3-04 PostgreSQL suite | 2 passed using isolated temporary databases |
| Architecture Fitness plus PostgreSQL | 295 passed |
| Forced RLS | Verified on all 6 tables under a non-owner, non-bypass role |
| Migration rehearsal | Empty, repeated upgrade, downgrade, and re-upgrade passed |
| Guarded populated rollback | Passed; downgrade rejected with reviewed forward-fix/export instruction |
| Claim replay | Equivalent input converges; changed source/span derivation fails closed |
| Timeline replay/rebuild | Stable ordering, duplicate collapse, changed-input denial, removal, and checkpoint checksum passed |
| Source disposition | Durable request, duplicate collapse, claim invalidation, timeline removal, and replay passed |
| Changed-scope Ruff | Passed for every changed Python file |
| Docker build and smoke | Production image `atlas-h3-04`, API import, and durable-worker smoke passed |
| Protected GitHub required gate | Passed on PR #32: Architecture Fitness, Regression Tests, Docker Build and Smoke, and H0 Required Gate |

## 7. Security and residual risk

Negative tests and constraints cover missing or cross-workspace context, forced RLS,
resource/version/chunk/hash substitution, unverified or deleted evidence, invalid
source spans, type confusion, confidence and validity bounds, changed derivation
input, classification downgrade, self-contradiction, audit/timeline conflation,
timeline replay mutation, source disposition replay, populated rollback, provider
leakage, and H3-05+ scope leakage. Events contain safe identifiers, versions, state,
and checksums rather than claim source content or raw exceptions.

No critical or high H3-04 security finding is known. Knowledge remains a derivative
data plane and cannot mutate operational aggregates. Timeline remains rebuildable and
does not replace immutable H1 audit evidence.

## 8. Compatibility and next-slice boundary

The change is additive and exposes no new HTTP API. Existing Gmail, Calendar, Drive,
Atlas chat, H0, H1, H2, and H3-01 through H3-03 runtime behavior remains unchanged.
PR #32 is merged into `origin/master` at `38c326d`; revision
`0025_h3_knowledge_timeline` is the accepted production migration baseline. The H3-04
slice is formally Accepted. H3-05 has not started; its implementation gate is owned by
the governance impacts and authorization in `H3_IMPLEMENTATION_GUIDE.md`.
