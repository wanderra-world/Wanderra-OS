# H2-02 Managed Connection Credentials Acceptance Evidence

**Owner:** Atlas Core
**Slice:** H2-02 — Managed connection credentials and migration inventory
**Status:** Implemented and locally verified; pull-request gate pending
**Date:** 31 July 2026
**Governing specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-02-managed-connection-credentials-and-migration-inventory)

## Scope and exclusions

H2-02 adds only managed, workspace-scoped connection credential metadata, authenticated
envelope context, Phase 1 inventory and shadow-verification evidence, replay-safe
migration, and credential generation availability controls.

Phase 1 Gmail, Calendar, and Drive encrypted payloads remain authoritative and
unchanged. The slice adds no OAuth transaction, callback dispatch, provider capability
execution, provider SDK use, mirror, HTTP API, route cutover, background worker, or
H2-03 and later functionality.

## Implementation evidence

- Provider-neutral contracts and redacted ephemeral snapshot:
  [app/connection_credentials/contracts.py](app/connection_credentials/contracts.py)
- Tenant-owned custody and inventory models:
  [app/connection_credentials/models.py](app/connection_credentials/models.py)
- Execution-context-bound repository and advisory-lock replay control:
  [app/connection_credentials/repository.py](app/connection_credentials/repository.py)
- Transactional shadow migration, rotation, revocation, reauthorization, and emergency
  disable service:
  [app/connection_credentials/service.py](app/connection_credentials/service.py)
- Isolated Phase 1 shadow-evidence adapter:
  [app/connection_credentials/phase_one.py](app/connection_credentials/phase_one.py)
- Additive migration:
  [alembic/versions/0015_add_connection_credentials.py](alembic/versions/0015_add_connection_credentials.py)
- Unit and redaction evidence:
  [tests/connection_credentials/test_h2_02_contracts.py](tests/connection_credentials/test_h2_02_contracts.py)
- PostgreSQL, RLS, migration, concurrency, and failure evidence:
  [tests/connection_credentials/test_h2_02_postgres.py](tests/connection_credentials/test_h2_02_postgres.py)
- Slice-isolation fitness evidence:
  [tests/architecture/test_h2_02_credential_scope.py](tests/architecture/test_h2_02_credential_scope.py)
- Operational recovery procedure:
  [H2_02_CREDENTIAL_OPERATIONS.md](H2_02_CREDENTIAL_OPERATIONS.md)

## Security and tenancy evidence

- The H1 AES-256-GCM managed-envelope boundary remains the only persistence path for
  new credential meaning. Plaintext exists only in process memory during encryption
  and comparison.
- Authenticated data binds workspace, connection, record identity, format version, and
  a record type containing provider, credential kind, and credential generation.
- PostgreSQL additionally rejects an envelope whose connection, record identifier, or
  authenticated record type differs from the credential metadata.
- Snapshot representations redact both plaintext and legacy ciphertext.
- Audit and outbox payloads contain identifiers, lifecycle metadata, reasons, and
  generation/version numbers only.
- `connection_credentials` and `credential_migration_inventory` have enabled and
  forced RLS with deny-by-default workspace policies.
- Composite foreign keys prevent a credential from referencing a connection, provider,
  envelope, or inventory item outside its workspace.
- H1 execution context and authorization are required before every service and
  repository operation.
- KMS outage, authenticated-context mismatch, changed legacy checksum, missing scope,
  disabled envelope, and invalid lifecycle state fail closed.
- The existing H1 encryption suite continues to cover corrupted ciphertext, revoked
  key versions, and wrong-context decryption.

No plaintext credential, raw token, legacy ciphertext, data-encryption key, wrapped
key, or provider response is emitted through logs, audit, outbox, exceptions, test
failure text, or committed evidence.

## Inventory, replay, and equivalence evidence

- Each Phase 1 source row is uniquely identified by workspace, source system, and
  source record identifier.
- Inventory persists only the SHA-256 legacy ciphertext checksum, normalized scope
  list, eligibility/status, attempt count, exception code, and verification references.
- Inventory summary deterministically reports row, eligible, verified, and exception
  counts plus an aggregate checksum and normalized scope inventory.
- A PostgreSQL transaction advisory lock serializes concurrent attempts for the same
  source row.
- Two concurrent attempts and subsequent replay return one verified credential
  generation and one inventory record.
- Reuse with changed legacy ciphertext is denied.
- JSON credential meaning is canonicalized before constant-time H1 shadow comparison.
- Missing required scopes persist a reauthorization-required exception without
  creating a credential or changing the legacy row.

## Migration and rollback evidence

**Revision:** `0015_h2_credentials`
**Predecessor:** `0014_h2_connections`

The migration:

- adds two empty H2-02 tenant tables and one connection candidate key;
- leaves all Phase 1 columns, ciphertext, routes, and reads in place;
- enables and forces RLS before runtime use;
- attaches the accepted H1 closed-workspace write freeze;
- enforces immutable credential/envelope identity at the database boundary;
- upgrades from an empty database and succeeds on repeated upgrade;
- downgrades safely while both H2-02 tables are empty;
- refuses downgrade after custody or inventory evidence exists and requires a reviewed
  forward fix.

The migration-only Phase 1 adapter writes `envelope_id`,
`envelope_legacy_checksum`, and `envelope_verified_at` after equivalence succeeds. It
does not modify `encrypted_payload`, does not set `envelope_cutover`, and performs no
provider operation.

## Verification results

With PostgreSQL 16 and the production dependency set:

```text
Focused H2-02 Ruff
All checks passed

Focused H2-02 tests
15 passed

Architecture Fitness
255 passed

Complete non-architecture regression suite
110 passed, 1 accepted deprecation warning

Production Docker build
atlas-h2-02 built successfully

Production image smoke
FastAPI application, H2-02 service, and ORM model imported successfully
```

The complete committed inventory is **365 passing tests**. The warning is the accepted
Starlette/httpx deprecation warning and is unrelated to H2-02.

## Compatibility and operational impact

- Existing Gmail, Calendar, Drive, Atlas chat, health, and OpenAPI behavior is
  unchanged.
- No H2-02 HTTP route or provider runtime dependency exists.
- Phase 1 credentials remain the only active read path.
- Valid legacy authorization remains available after KMS failure, scope exception,
  partial shadow migration, rotation, revocation, or emergency disable of an H2
  generation.
- The production migration count becomes 15 after deployment.
- Application rollback retains the additive schema. Schema downgrade is safe only
  before H2-02 state exists; otherwise use the documented forward-fix path.

## Open findings

No unresolved critical, high, medium, or low H2-02 finding remains.

The repository retains one pre-existing Starlette/httpx deprecation warning. It is
owned by Atlas Platform Engineering under the existing compatibility-cleanup baseline
and does not affect credential custody, runtime behavior, or the required gate.

## Pull-request gate

Dedicated pull request: pending creation.

The protected checks required before acceptance are:

- `H0 Required / Architecture Fitness`;
- `H0 Required / Regression Tests`;
- `H0 Required / Docker Build and Smoke`;
- `H0 Required / H0 Required Gate`.

H2-02 remains pending acceptance until all checks pass and the pull request is merged.
No H2-03 work has started.
