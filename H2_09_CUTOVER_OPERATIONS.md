# H2-09 Connection Cutover Operations

**Owner:** Atlas Platform Engineering  
**Compatibility removal owner:** Atlas Core  
**Removal gate:** H7 Phase 1 compatibility removal  
**Maximum rollback window:** Until the H7 removal gate is explicitly accepted

This runbook implements the H2-09 operational controls defined in
`H2_PLATFORM_SPEC.md`. It does not authorize removal of a Phase 1 path.

## Backfill

1. Inventory Gmail, Calendar, and Drive credential rows by default workspace and
   provider account.
2. Calculate source SHA-256 checksums without logging credential content.
3. Generate the deterministic workspace-suite connection ID.
4. Create one connection for the account, or verify the existing deterministic
   connection has the same provider account.
5. Bind each source record to immutable backfill evidence.
6. Mark an ineligible credential as `reauthorization_required`; do not invalidate a
   valid legacy credential.
7. Re-run the backfill and confirm the connection ID, counts, source checksums, and
   evidence checksum are identical.

Backfill is transaction-owned, workspace-bound, idempotent, and restartable. A replay
whose source or evidence checksum changes fails closed and requires reconciliation.

## Cutover sequence

For each workspace connection and capability:

1. Keep read and mutation routes on `legacy`.
2. Move the read route to `shadow`.
3. Collect at least ten comparisons with a zero-mismatch failure budget.
4. Investigate any mismatch; canonical routing remains denied while the failure budget
   is exceeded.
5. Move the read route to `canonical` through the authorized cutover service.
6. Move the mutation route to `canonical` only after the same read-shadow threshold
   passes. Approval, authorization, idempotency, preconditions, and post-write
   verification remain capability-service responsibilities.
7. Verify transactional audit, outbox, and immutable cutover evidence.

The threshold is explicit per cutover decision. A denied attempt is recorded without
changing either route.

## Rollback

Set the affected read and mutation routes to `legacy`. Rollback does not require a
shadow threshold and never modifies provider credentials, provider resources, mirror
identity, or Phase 1 tables. Verify Phase 1 API behavior immediately after the route
change and reconcile any already-completed provider mutation from its receipt.

Application rollback and schema downgrade are separate. Revision
`0021_h2_connection_cutover` downgrades only while no backfill/cutover evidence exists
and every mutation route remains `legacy`; otherwise use a reviewed forward fix.

## Failure and reauthorization

- Insufficient samples or a mismatch keeps canonical routing disabled.
- A source-checksum change stops replay and requires inventory reconciliation.
- Missing or ineligible managed credentials produce an explicit
  `reauthorization_required` exception while the legacy path remains available.
- A provider failure uses the existing canonical error, idempotency, version, and
  verification contracts; it never triggers an automatic blind route change.
- Closure disables connection credentials, closes connections, restores legacy route
  flags, and retains provider reconciliation evidence without deleting provider data.

## Compatibility inventory

| Compatibility surface | Owner | Removal gate |
|---|---|---|
| Gmail Phase 1 service and credential table | Atlas Core | H7 |
| Calendar Phase 1 service and credential table | Atlas Core | H7 |
| Drive Phase 1 service, credential table, and metadata table | Atlas Core | H7 |
| Shared Gmail callback URL compatibility | Atlas Core | H7 |
| Legacy route in email/calendar/storage capability services | Atlas Core | H7 |
| Phase 1 credential fallback during reauthorization | Atlas Core | H7 |

No compatibility surface may be removed during H2.
