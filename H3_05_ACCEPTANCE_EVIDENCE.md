# H3-05 Memory Manager Acceptance Evidence

**Owner:** Atlas Platform Engineering

**Status:** Implemented; pending pull-request acceptance

**Governing specification:** [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md#h3-05-memory-manager)

**Engineering contract:** [H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md#121-h3-05-accepted-security-review-scope)

## 1. Prerequisites

- H3-04 is Accepted and merged through PR #32 at `38c326d`.
- PR #33 is merged into `origin/master` at `1fb3dc4` and explicitly opens H3-05.
- The H0, H1, H2, H3-01, H3-02, H3-03, and H3-04 accepted baselines were verified.
- The governing architecture, implementation, exit, index, project-status, ADR, and
  prior-slice evidence documents were reread from `origin/master` before branching.

## 2. Implemented scope

- Typed governed-memory, source, consolidation, feedback, lifecycle, visibility,
  classification, expiry, model-route, and error contracts.
- Deterministic content-and-provenance identity with equivalent replay convergence.
- Required provenance to H3-01 resources, verified H3-03 document versions, H3-04
  claims, or active governed-memory inputs, revalidated when memory is retrieved.
- Versioned deterministic consolidation with exact input identity, source state,
  processor version, input digest, and monotonic classification.
- Pin/unpin, human confirmation, durable feedback, expiry, supersession, deletion,
  and transitive invalidation after source deletion, permission revocation, or
  workspace closure.
- Recovery/export manifests and immutable disposition receipts without treating
  memory as operational truth or audit evidence.
- H1 authorization, canonical execution context, audit, transactional outbox,
  composite tenant identity, closed-workspace protection, and forced RLS.

## 3. Explicit exclusions

No HTTP API, embedding, vector index, retrieval ranking, search, recommendation,
planner, workflow, notification, provider adapter, provider-specific behavior,
business agent, H3-06+, or H4 functionality is introduced. Existing Phase 1 memory
retrieval remains unchanged and separate.

## 4. Migration and rollback

- Revision: `0026_h3_governed_memory`.
- Parent: accepted H3-04 revision `0025_h3_knowledge_timeline`.
- Four additive tenant tables: governed memory items, sources, feedback, and
  dispositions.
- Composite tenant foreign keys prevent cross-workspace references. Every table has
  enabled and forced RLS plus closed-workspace write protection.
- Empty upgrade, repeated upgrade, downgrade to H3-04, and re-upgrade pass.
- Populated downgrade fails closed and requires reviewed forward fix/export.
- No accepted table, route, API, or runtime behavior is rewritten.

## 5. Red → Green → Refactor evidence

Red began with contract and architecture tests failing because the governed-memory
contracts did not exist. Green added only H3-05 contracts and the minimum context-bound
persistence/service implementation. Refactor tightened document-version hash custody,
feedback aggregate sequencing, supersession integrity, transitive invalidation, and
deterministic export while the focused suite remained green.

## 6. Verification evidence

| Verification | Result |
|---|---|
| New H3-05 tests | 13 tests: 7 contract, 4 architecture, and 2 isolated PostgreSQL acceptance tests |
| Focused contract and architecture tests | 11 passed |
| H3-05 PostgreSQL suite | 2 passed |
| Complete local Architecture Fitness | 322 passed against PostgreSQL 16 |
| Complete local non-architecture regression | 372 passed; one pre-existing Starlette/httpx deprecation warning |
| Forced RLS | Verified on all four H3-05 tables under a non-owner, non-bypass role |
| Migration rehearsal | Empty, repeated upgrade, downgrade, and re-upgrade passed |
| Populated rollback | Failed closed with reviewed-forward-fix/export instruction |
| Ruff required scope | Passed for Architecture Fitness and every changed Python file |
| Repository-wide Ruff audit | 102 pre-existing Phase 1 findings remain outside H3-05; no new finding in changed scope |
| Docker build and smoke | `atlas-h3-05` built; API import and durable-worker smoke passed |
| Protected GitHub required gate | Passed on PR #34: Architecture Fitness, Regression Tests, Docker Build and Smoke, and H0 Required Gate |

The local workspace contains unrelated untracked duplicate files suffixed ` 2.py`.
They are excluded from this change; local repository-wide collection therefore has a
higher count than clean-checkout CI. The dedicated H3-05 count above includes only
new canonical files.

## 7. Security and residual risk

Negative tests and constraints cover missing provenance, changed replay input,
classification downgrade, naive expiry, unbounded content, restricted model egress,
source substitution, stale source version/digest, cross-workspace access, forced RLS,
supersession integrity, expiry/pinning precedence, transitive invalidation, populated
rollback, provider leakage, and later-slice leakage. Audit and outbox payloads contain
only governed identifiers, status, and versions—not memory content.

No critical or high H3-05 security finding is known. Residual model-egress risk is
bounded by classification and private-route enforcement; model invocation itself is
outside this slice.

## 8. Compatibility and next-slice boundary

The change is additive and exposes no new HTTP API. Existing Gmail, Calendar, Drive,
Atlas chat, H0, H1, H2, and H3-01 through H3-04 behavior remains unchanged. Revision
`0026_h3_governed_memory` is proposed, not accepted, until this pull request merges.
H3-06 and later slices, H4, provider-specific behavior, and business agents remain
unauthorized and have not started.
