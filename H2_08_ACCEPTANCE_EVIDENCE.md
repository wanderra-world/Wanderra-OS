# H2-08 Acceptance Evidence

**Owner:** Atlas Platform Engineering  
**Specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-08-google-drive-adapter-and-storage-shadow-migration)  
**Status:** Implementation complete; pull-request acceptance pending  
**Date:** 31 July 2026

## Scope

H2-08 moves existing Drive list, search, metadata, download, upload, update, delete,
Google Docs, PDF, and DOCX behavior behind the canonical storage port. It adds no H5
document custody, extraction framework, change feed, resumable product API, worker,
cutover default, or H2-09+ behavior.

## Implementation evidence

- Google Drive SDK adapter confined to `app/integrations/drive`.
- Canonical identity, MIME, size, checksum, version, timestamps, parents, pagination,
  safe errors, and namespaced extension translation.
- Managed H2-02 credential loading and provider-mirror observer boundary.
- Legacy, shadow, and canonical per-workspace routing; shadow returns legacy output.
- Binary content remains transient and is never persisted in the H2-08 tables.
- Google Docs export plus PDF and DOCX readable-text projections.
- Approval-gated and idempotent upload/update/delete with version preconditions and
  provider post-write/absence verification.
- Audited route control and transactional outbox evidence.
- Additive forced-RLS migration `0020_h2_storage_capability` with guarded rollback.

## Test evidence

- Adapter/content/mutation tests: `tests/storage_capability/test_h2_08_google_adapter.py`.
- Routing/security tests: `tests/storage_capability/test_h2_08_routing.py`.
- PostgreSQL/RLS/rollback tests: `tests/storage_capability/test_h2_08_postgres.py`.
- SDK and document-custody fitness: `tests/architecture/test_h2_08_drive_scope.py`.
- Shared storage conformance and complete Phase 1 regression suites.

Local verification on 31 July 2026 produced:

- complete PostgreSQL-enabled suite: `464 passed`;
- Architecture Fitness: `267 passed, 4 skipped`;
- Ruff on every changed Python and migration file: passed;
- Docker production build and smoke import: passed.

Final acceptance additionally requires the pull request's mandatory GitHub gate.

## Rollback

Setting the workspace connection route to `legacy` restores Phase 1 behavior without
changing credentials or repeating provider effects. Empty H2-08 tables may downgrade
to `0019_h2_calendar_capability`; populated evidence blocks downgrade and requires a
reviewed forward fix.

## Slice isolation

H2-09 has not been started. There is no connection backfill, cutover threshold,
default-route transition, compatibility removal, worker, webhook, or document custody.
