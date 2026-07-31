# H2-09 Acceptance Evidence

## Scope

H2-09 implements deterministic connection backfill, credential eligibility linkage,
shadow-metric thresholds, independent read and mutation cutover controls, reversible
legacy routing, and H2 recovery/export/closure coverage. It adds no provider
capability, worker, webhook, synchronization runtime, H3 concept, or H2-10 work.

## Implementation evidence

- `app/connection_cutover/` owns provider-neutral backfill, threshold, evidence,
  repository, and cutover services.
- Gmail, Calendar, and Drive retain legacy, shadow-read, and canonical routes. Mutation
  routing is separately controlled and defaults to legacy.
- Canonical read cutover requires legacy → shadow → canonical and a configured
  comparison threshold. Mutation cutover requires the same passing shadow evidence.
- Rollback to legacy is always available and does not alter credentials or provider
  resources.
- Recovery manifests include every H2 tenant table. Closure disables credentials,
  closes connections, restores legacy route flags, and preserves provider
  reconciliation evidence.
- Compatibility ownership and the H7 removal milestone are recorded in
  `H2_09_CUTOVER_OPERATIONS.md`.

## Migration evidence

- Revision: `0021_h2_connection_cutover`
- Previous revision: `0020_h2_storage_capability`
- Adds two workspace-owned evidence tables with composite keys, forced RLS, write-state
  triggers, and immutable cutover evidence.
- Adds a backward-compatible `mutation_route` column defaulting to `legacy` to each
  accepted capability route table.
- Empty/shadow-free downgrade is tested. Backfill evidence, cutover evidence, or a
  canonical mutation route blocks lossy downgrade and requires a reviewed forward fix.
- Phase 1 credential tables, columns, APIs, and provider resources are not removed.

## Security and compatibility evidence

- Execution context and workspace-bound repositories reject cross-workspace access.
- Authorization runs before a cutover decision; denied thresholds do not mutate route
  state.
- Successful cutovers atomically record immutable decision evidence, audit, and outbox
  records.
- Backfill replay validates stable identity and source/evidence checksums.
- Existing approval, idempotency, version-precondition, and post-write verification
  boundaries remain unchanged.

## Reproducible verification

- H2-09 contract and architecture tests cover deterministic planning, restartability,
  reauthorization exceptions, thresholds, rollback, H2 manifest completeness, and
  H2-10 exclusion.
- PostgreSQL tests cover populated Phase 1 migration, repeated upgrade, forced RLS,
  independent read/mutation cutover, audit/outbox evidence, and empty rollback.
- The complete repository regression, Architecture Fitness, Ruff, Docker build, smoke,
  and GitHub Required Gate results are recorded in the dedicated H2-09 pull request.

## Findings and later-slice exclusion

No unresolved critical or high finding is known. Phase 1 compatibility remains owned
by Atlas Core until H7. H2-10 has not been started.
