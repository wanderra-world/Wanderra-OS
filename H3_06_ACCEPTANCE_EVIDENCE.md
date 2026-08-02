# H3-06 Search and Context Assembly Acceptance Evidence

**Owner:** Atlas Platform Engineering

**Status:** Accepted and merged through PR #36

**Governing specification:** `H3_ARCHITECTURE.md` H3-06 and
`H3_IMPLEMENTATION_GUIDE.md` sections 1.29–1.36

**Migration:** `0027_h3_search_context`, additive from accepted
`0026_h3_governed_memory`

## Scope delivered

- Provider-neutral search-document, ACL, embedding, generation, freshness, and
  reconciliation contracts and persistence.
- PostgreSQL `simple` full-text indexing and pgvector cosine-distance retrieval.
- Deterministic reciprocal-rank fusion, exact-match priority, structured filters, and
  graph expansion bounded to depth two.
- Workspace/user ACL predicates and current resource-state predicates in candidate SQL;
  similarity never grants authorization.
- Immutable source/version/digest, chunker, embedding, policy, classification, and
  index-generation lineage for every result.
- Classification-preserving context fragments treated as untrusted source data, with
  citations, deterministic truncation, approved budgets, and restricted/private route
  enforcement.
- Idempotent source disposal, auditable reconciliation, lexical rollback, concurrent
  index-generation coexistence, and H3-02 durable reindex/cleanup job envelopes.
- Transactional audit and outbox evidence without governed content in event payloads.

## Security and isolation evidence

Candidate queries join active ACL projections before ranking and are tenant-bound by
the immutable execution context and forced PostgreSQL RLS. Current resource status is
also checked before retrieval. Private documents receive only an actor principal;
workspace and restricted documents receive the workspace principal while model egress
remains independently classification-gated. Disposed sources become unavailable in the
same transaction, while idempotent cleanup remains retryable.

The context API returns structured, `untrusted=True` fragments and never interprets
source text as instructions. Restricted fragments fail closed unless the private model
route is selected. H3-06 contains no model call, answer generation, agent, provider,
connector, or business logic.

## Quality and operational evidence

The deterministic 102-query/three-workspace corpus verifies recall@10 `1.00`, NDCG@10
`1.00`, citation coverage `100%`, and zero unauthorized candidates. PostgreSQL tests
verify lexical retrieval, immediate source disposition, idempotent replay, pgvector
availability, forced RLS, migration rehearsal, empty rollback, and populated rollback
refusal. The repository retains lexical retrieval when embeddings are absent and can
disable an active vector generation without contracting stored evidence.

The approved 100,000-record production latency threshold remains an operational SLO;
the implementation supplies indexed PostgreSQL query plans and bounded candidate sets,
and CI guards correctness. Production telemetry must continuously measure p95/p99,
freshness, cleanup, and authorization failure rates after deployment.

## Verification commands

Recorded local results on 2 August 2026:

- H3-06 slice tests: **11 passed**, including three real PostgreSQL/pgvector tests.
- Complete tracked Architecture Fitness suite with PostgreSQL/RLS: **299 passed**.
- Complete tracked non-architecture regression suite with PostgreSQL: **255 passed**.
- Ruff: all changed production, migration, H3-06 test, and complete tracked
  Architecture Fitness sources pass; the required CI Ruff command passes.
- Migration: full upgrade to `0027_h3_search_context`, repeatable rehearsal, empty
  downgrade to `0026_h3_governed_memory`, re-upgrade, and populated downgrade refusal
  pass against PostgreSQL 16 with pgvector.
- Docker: production image `atlas-h3-06` builds successfully; application import and
  durable worker smoke tests pass.
- GitHub PR #36 `H0 Required / H0 Required Gate`: **passed**, including Architecture
  Fitness, Regression Tests, and Docker Build and Smoke.

## Slice isolation

PR #36 is merged into `origin/master` at `a34322e`; revision
`0027_h3_search_context` is the accepted production migration baseline and H3-06 is
formally Accepted. H3-07 remains unimplemented; its implementation gate is owned by
the governance impacts and authorization in `H3_IMPLEMENTATION_GUIDE.md`. H3-08 and
later slices, H4, provider-specific integrations, connectors, business agents, UI,
external search services, and Phase 1 API changes remain unauthorized and have not
started.
