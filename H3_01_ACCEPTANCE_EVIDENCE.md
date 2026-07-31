# H3-01 Resource Graph Acceptance Evidence

**Owner:** Atlas Platform Engineering  
**Status:** Implementation complete; PR #26 ready for review with required gate passed  
**Governing specification:** [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md#h3-01-resource-graph-foundation)  
**Engineering contract:** [H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md)

## 1. Prerequisites

- Formal H2 Exit remains accepted at PR #23.
- PR #24 approved the H3 blueprint.
- PR #25 formally accepted ADR-033 and opened the sequential H3 implementation gate;
  it is merged into `origin/master` as `a60d1e8`.
- The user explicitly authorized H3-01 only.
- ADR-003, ADR-028, the H0 projection-integrity contract, and the accepted H3-01
  security and migration plans were reread before branching.

## 2. Implemented scope

- Atlas-controlled resource kinds for contact, company, project, task,
  communication, meeting, and document only.
- A cyclic, deferred, one-to-one resource/projection binding that rejects orphaned or
  duplicated identities at commit.
- Typed and directed relationship contracts with database and service validation,
  cardinality enforcement, workspace-safe endpoints, and soft deletion.
- Workspace-owned tags, document attachment references, human/AI notes with AI model
  provenance, ownership, exceptional resource grants, and immutable H2 provider
  external-reference links.
- Canonical execution-context enforcement, H1 authorization, optimistic versions,
  audit records, and transactional outbox events.
- Organization/workspace/cell composite tenant keys, closed-workspace write guards,
  and enabled and forced PostgreSQL RLS on every H3-01 tenant table.

## 3. Explicit exclusions

H3-01 introduces no arbitrary EAV fields, business aggregates, knowledge graph,
document custody, search, embeddings, jobs, scheduler, workflows, notifications,
planner, orchestrator, business agent, provider adapter, or H3-02+ functionality.
H2 production contracts and compatibility behavior are unchanged.

## 4. Migration and rollback

- Revision: `0022_h3_resource_graph`.
- Parent: accepted H2 head `0021_h2_connection_cutover`.
- The migration is additive and performs no H2 rewrite or destructive contraction.
- Empty-state upgrade, repeated upgrade, downgrade to H2, and re-upgrade pass.
- Once resource, resource audit, or resource outbox state exists, downgrade fails
  closed and requires a reviewed forward-fix.
- Provider external-reference identity and linkage are immutable.

## 5. Red → Green → Refactor evidence

Red began with missing `app.resource_graph` contracts and a missing H3-01 migration.
Green introduced only the minimum Resource Graph contracts, persistence, repository,
service, migration, and tests. Refactoring replaced generic registry insertion with an
atomic pair repository operation, centralized feature persistence, applied
authorization before resource retrieval, and made relationship deletion explicit.

## 6. Verification evidence

| Verification | Result |
|---|---|
| H3-01 domain and PostgreSQL tests | 7 passed against PostgreSQL 16 |
| Migration and empty rollback rehearsal | Passed |
| Guarded populated downgrade | Passed; rejected with forward-fix instruction |
| Forced RLS | Passed on all 9 H3-01 tenant tables |
| Projection orphan/duplicate constraints | Passed |
| Cross-workspace access | Denied |
| Relationship type/direction/cardinality | Passed |
| Optimistic concurrency | Stale update denied |
| Resource grants | Explicit read grant verified; H1 execution context remains mandatory |
| Provider-neutral external link | H2 storage-file reference linked without provider payload leakage |
| Audit/outbox | State changes emitted matching atomic evidence |
| H3-01 and architecture Ruff checks | Passed |
| Complete regression suite | 491 passed against PostgreSQL 16 |
| Docker build and production smoke | Passed with `atlas-h3-01` production image |
| Protected GitHub required gate | PR #26 passed Architecture Fitness, Regression Tests, Docker Build and Smoke, and H0 Required Gate |

## 7. Security and residual risk

The accepted H3-01 threat paths have negative tests or database constraints for
unapproved types, orphan identity, cross-workspace access, endpoint substitution,
relationship direction/cardinality, stale versions, grant escalation, provider
reference substitution, deletion integrity, provider leakage, EAV introduction, and
H3-02 leakage. No critical or high unresolved H3-01 finding is known.

## 8. Compatibility and next-slice boundary

The change is additive and exposes no new Phase 1 API. Gmail, Calendar, Drive, H0,
H1, and H2 runtime behavior remains unchanged. H3-02 has not been started and is not
authorized by this evidence.
