# H1-09 Recovery and Closure Operations

**Owner:** Atlas Platform Engineering  
**Status:** H1-09 implementation procedure  
**Scope:** H1-owned workspace data only

This runbook records the operational use of the recovery and closure contracts
implemented by H1-09. It does not redefine architecture. The governing requirements
remain in `H1_PLATFORM_SPEC.md`.

## Encrypted PostgreSQL backup

1. Select an approved immutable managed-KMS key version.
2. Start a repeatable-read PostgreSQL transaction and record its snapshot timestamp.
3. Generate a PostgreSQL custom-format dump with `pg_dump --format=custom
   --no-owner --no-privileges`. The dump must cover the complete database so relational
   constraints, RLS policies, triggers, audit chains, and outbox state are retained.
4. Build the workspace H1 manifest inside the same snapshot. It contains counts and
   SHA-256 digests, never row contents or provider secrets.
5. Pass the dump bytes and manifest to `EncryptedBackupService.create`. The service:

   - generates a random AES-256 data-encryption key;
   - authenticates the backup ID, workspace, and immutable KMS key version;
   - wraps the data key through the canonical managed `KeyProvider`;
   - records the plaintext checksum only inside protected backup metadata;
   - rejects a snapshot older than the approved 15-minute PostgreSQL RPO.

6. Store the encrypted artifact and wrapped key in the approved backup vault. Never
   persist the plaintext dump or raw data-encryption key.
7. Record backup evidence without credentials, plaintext, tokens, or ciphertext in
   audit details.

## Isolated restore rehearsal

1. Create a new isolated PostgreSQL database with no application traffic.
2. Retrieve the encrypted backup and immutable KMS key reference.
3. Decrypt in memory through `EncryptedBackupService.restore`. Missing, disabled, or
   incorrect key access must fail closed.
4. Restore using `pg_restore --clean --if-exists --no-owner --no-privileges` into the
   isolated database only. Never restore over a live database.
5. Run migrations only when the reviewed recovery plan explicitly requires them.
6. Recompute the H1 manifest and require exact count and digest equality.
7. Verify:

   - forced RLS and non-bypass runtime roles;
   - managed-key decrypt access and key-version references;
   - `verify_audit_chain(workspace_id)`;
   - pending and published outbox state;
   - membership and session revocation state.

8. Record measured RPO and RTO. The accepted targets are 15 minutes and four hours.
9. Destroy the isolated environment after the evidence is reviewed.
10. Record provider reconciliation as required but do not execute it in H1. Provider
    reconciliation and Phase 1 mirror migration remain H2 dependencies.

## Workspace export

`WorkspaceRecoveryService.create_export` produces a versioned, idempotent manifest for
H1-owned workspace tables. It contains table counts and digests only. Gmail, Calendar,
Drive, documents, provider content, Phase 1 memory, and content bundles are excluded.
The caller must provide the authorization decision from the current execution context.

## Workspace closure

Closure is an explicitly authorized, idempotent operation:

1. Lock the canonical workspace.
2. Capture the before-manifest.
3. Revoke H1 sessions, lifecycle tokens, and memberships immediately.
4. Disable managed credential envelopes and freeze ordinary H1 writes.
5. Evaluate legal hold, then minimum retention.
6. When blocked, keep the workspace in `retention_blocked`; do not erase governed data.
7. When eligible, erase H1 sessions, lifecycle tokens, notifications, encrypted
   envelopes, consumer state, quarantines, and command state.
8. Preserve minimal immutable audit, outbox, membership-revocation, export, governance,
   and closure evidence.
9. Mark the workspace closed, verify the after-manifest, and issue an immutable
   SHA-256 closure receipt.

Phase 1 provider credentials and provider data are deliberately untouched. Every
receipt states that provider reconciliation remains required and that Phase 1 provider
data was not erased.

## Failure and rollback rules

- Backup authentication, checksum, KMS access, manifest equality, RPO, or RTO failures
  stop the operation and require reviewed recovery action.
- Ordinary H1 writes remain denied after closure begins.
- Legal hold and minimum retention always override erasure.
- Migration `0013_h1_recovery_closure` can be downgraded only before recovery,
  governance, export, or closure state exists. Otherwise a reviewed forward fix is
  mandatory.
- Closure receipts, exports, and recovery evidence are immutable.
