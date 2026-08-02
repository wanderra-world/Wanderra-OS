# H3-03 Documents and Governed Derivation Acceptance Evidence

**Owner:** Atlas Platform Engineering  
**Status:** Implementation complete on dedicated branch; formal acceptance pending  
**Governing specification:** [H3_ARCHITECTURE.md](H3_ARCHITECTURE.md#h3-03-documents-and-governed-derivation)  
**Engineering contract:** [H3_IMPLEMENTATION_GUIDE.md](H3_IMPLEMENTATION_GUIDE.md#16-h3-03-accepted-security-review-scope)

## 1. Prerequisites

- H3-02 is Accepted and merged through PR #28 at `915386c`.
- PR #29 opened the H3-03 gate and is merged into `origin/master` at `24284e8`.
- The complete H3 architecture, implementation guide, exit definition, Architecture
  Index, project status, H2 specification, and repository engineering contract were
  reread from the merged baseline.
- The user explicitly authorized H3-03 only.
- The approved H3-03 security, classification, custody, retention, deletion,
  recovery, migration, and rollback constraints were verified before branching.

## 2. Implemented scope

- Canonical typed documents linked one-to-one to H3-01 document resources.
- Immutable, content-addressed versions with quarantine and canonical object keys,
  SHA-256 custody evidence, media type, malware verdict, classification-policy
  version, encryption-key version, and optional H2 external-reference lineage.
- Quarantine-first verification and explicit promotion through a provider-neutral
  storage port. Hash substitution, malware, and invalid media evidence fail closed.
- Deterministic, content-derived extraction inputs and replay-safe derivatives and
  chunks with complete source-version, processor, classification, and policy lineage.
- H3-02 durable extraction and deletion job adapters carrying identifiers and input
  digests rather than document content.
- Legal-hold and retention precedence, explicitly authorized governance changes,
  durable deletion requests, retryable exception evidence, and idempotent recovery.
- Recovery/export manifests and restore-time content-hash verification.
- Atomic H1 audit and transactional outbox evidence for material state transitions.

## 3. Explicit exclusions

No HTTP API, Phase 1 route change, provider implementation, provider SDK use,
knowledge extraction semantics, memory, embeddings, search, notification delivery,
workflow, planner, business agent, H3-04+, or H4 functionality is introduced.

## 4. Migration and rollback

- Revision: `0024_h3_document_custody`.
- Parent: accepted H3-02 revision `0023_h3_durable_execution`.
- Five additive tenant tables: documents, versions, derivatives, chunks, and deletion
  records.
- Every table has organization/workspace/cell composite identity, workspace-consistent
  foreign keys, closed-workspace write protection, and enabled and forced RLS before
  runtime access.
- Empty upgrade, repeated upgrade, downgrade to H3-02, and re-upgrade pass.
- Populated downgrade fails closed with a reviewed-forward-fix/export instruction.
- Application rollback preserves existing H3-03 state because no existing API or
  runtime path depends on the additive tables.

## 5. Red → Green → Refactor evidence

Red began with missing `app.documents` contracts, models, repository, service,
migration, and architecture boundary. Subsequent failing tests exposed missing durable
job adapters, duplicate outbox sequence numbers, synchronous deletion risk, and the
absence of an authorized retention/hold transition.

Green introduced only the H3-03 custody aggregate, provider-neutral ports,
transactional service, durable H3-02 adapters, five-table persistence boundary, and
additive migration required by those tests. Refactor serialized extraction replay,
made deletion a crash-safe two-transaction protocol, revalidated governance before
object deletion, and preserved retryable deletion exceptions without weakening any
earlier contract.

## 6. Verification evidence

| Verification | Result |
|---|---|
| New H3-03 tests | 14 tests across contracts, service, PostgreSQL, migration, RLS, recovery, and architecture boundaries |
| Complete local regression suite | 526 passed against PostgreSQL 16; one pre-existing Starlette/httpx deprecation warning |
| H3-03 PostgreSQL suite | 3 passed using isolated temporary databases |
| Architecture Fitness plus PostgreSQL | 290 passed |
| Forced RLS | Verified on all 5 tables under a non-owner, non-bypass role |
| Migration rehearsal | Empty, repeated upgrade, downgrade, and re-upgrade passed |
| Guarded populated rollback | Passed; downgrade rejected with reviewed forward-fix/export instruction |
| Extraction replay | Concurrently serialized source version; equivalent input converges on the existing derivative |
| Custody and recovery | Quarantine, verification, source lineage, export, restore hash, and deletion retry passed |
| Changed-scope Ruff | Passed for every changed Python file |
| Repository-wide Ruff baseline | 103 pre-existing Phase 1 findings outside H3-03; no new finding |
| Docker build | Passed with production image `atlas-h3-03` |
| API image smoke | Passed |
| Durable worker image smoke | Passed |
| Protected GitHub required gate | Passed for PR #30 (Architecture Fitness, Regression Tests, Docker Build and Smoke) |

## 7. Security and residual risk

Negative tests and constraints cover missing or cross-workspace context, forced RLS,
object substitution, malware and media rejection, extraction before verification,
classification downgrade, changed extraction input, legal hold, minimum retention,
object-deletion failure and retry, restore corruption, populated rollback, provider
SDK leakage, and H3-04+ scope leakage. Audit and outbox evidence contain identifiers,
versions, status, and safe codes rather than document content or raw exceptions.

No critical or high H3-03 security finding is known. The concrete production object
store, malware scanner, and extractor remain deployment-owned implementations of the
approved ports; H3-03 deliberately does not select a provider or expose an API.

## 8. Compatibility and next-slice boundary

The change is additive and exposes no new HTTP API. Existing Gmail, Calendar, Drive,
Atlas chat, H0, H1, H2, H3-01, and H3-02 runtime behavior remains unchanged. The
accepted production migration baseline remains `0023_h3_durable_execution` until the
dedicated H3-03 pull request is reviewed, its protected checks pass, and it is merged.
H3-04 has not started and remains unauthorized.
