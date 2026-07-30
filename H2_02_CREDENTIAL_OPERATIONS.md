# H2-02 Credential Migration and Recovery Runbook

**Owner:** Atlas Platform Engineering
**Governing specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-02-managed-connection-credentials-and-migration-inventory)
**Authority:** Operational procedure only; it does not authorize H2-03 or cutover.

## Invariants

- Phase 1 Gmail, Calendar, and Drive credential rows remain authoritative.
- Never set `envelope_cutover` during H2-02.
- Never delete or overwrite `encrypted_payload`.
- Run inventory and shadow operations inside a validated H1 execution context and one
  caller-owned transaction.
- Never place plaintext, raw tokens, legacy ciphertext, wrapped keys, or provider
  responses in logs, audit details, outbox payloads, tickets, or evidence files.

## Inventory and shadow procedure

1. Resolve the canonical workspace and H2-01 connection.
2. Decrypt one legacy credential only in process memory through the existing Phase 1
   custody boundary.
3. Record the legacy ciphertext checksum, normalized scopes, and source row identity.
4. Compare granted scopes with the required set. Record
   `reauthorization_required` and stop if any required scope is absent.
5. Encrypt the canonical credential meaning through the H1 managed-envelope service.
6. Decrypt the shadow and compare canonical meaning in constant time.
7. Link only the envelope identifier, legacy checksum, and verification timestamp back
   to the Phase 1 row. Keep `envelope_cutover = false`.
8. Verify inventory counts, aggregate checksum, exceptions, audit records, and outbox
   records before marking the rehearsal complete.

The service serializes each workspace/source-row pair with a PostgreSQL transaction
advisory lock. A replay with the same ciphertext checksum returns the verified
credential generation. A changed checksum fails and requires a new reviewed inventory.

## Failure response

| Failure | Required response |
|---|---|
| Managed key provider unavailable | Fail the shadow attempt; retain the Phase 1 row unchanged; retry with the same source after key service recovery |
| Ciphertext or authenticated context mismatch | Fail closed; quarantine the H1 envelope; investigate workspace, connection, provider, kind, and generation coordinates |
| Missing scope | Record `reauthorization_required`; retain the working legacy credential; authorization is owned by H2-03 |
| Partial or interrupted migration | Replay the same source row; advisory locking and checksum comparison prevent duplicates |
| Emergency disable | Disable the H1 envelope and H2 credential generation; do not alter the Phase 1 credential |
| Credential revocation | Revoke the H2 generation and disable its envelope; Phase 1 revocation or provider effects are outside H2-02 |

## Rollback and forward fix

- Downgrade from `0015_h2_credentials` to `0014_h2_connections` is allowed only when
  both H2-02 tables are empty.
- After any custody or inventory state exists, the migration refuses downgrade because
  deletion would destroy security evidence.
- Roll back application code while retaining the additive schema, then deploy a
  reviewed forward fix.
- Phase 1 APIs remain operational throughout because they continue reading the
  unchanged `encrypted_payload`.

## Verification

Before approval, run:

- H2-02 unit and architecture tests;
- PostgreSQL migration, RLS, concurrency, replay, and failure tests;
- the complete architecture and regression suites;
- Ruff on all changed files and architecture evidence;
- production Docker build and application smoke tests;
- the protected GitHub `H0 Required / H0 Required Gate`.
