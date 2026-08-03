# H3 Platform Operations Runbook

**Owner:** Atlas Platform Operations
**Scope:** Provider-neutral H3 observation, incident control, and recovery

## Operating rules

- Use authenticated application services with canonical execution context; never
  mutate PostgreSQL directly.
- Record a bounded reason, expected version, idempotency key, actor, correlation ID,
  and resulting audit evidence for every operator action.
- Treat uncertain outcomes as unresolved. Never retry an external effect without its
  accepted idempotency or version-precondition contract.
- Telemetry contains identifiers, numeric measurements, classifications, and bounded
  labels only—never credentials, governed payloads, raw prompts, or source content.

## Control map

| Boundary | Inspect/control path | Recovery verification |
|---|---|---|
| Durable jobs/schedules | H3-02 query, pause/resume, cancel, dead-letter and authorized replay services | Lease, attempt, idempotency, receipt and audit reconciliation |
| Documents/derivatives | H3-03 quarantine, verification, disposition and deletion services | Content hash and complete derivative inventory |
| Search/context | H3-06 generation pause, rebuild and reconciliation commands | Source version, ACL projection and generation checksum |
| Tasks | H3-07 lifecycle/reminder cancellation commands | Version and immutable completion evidence |
| Workflows/approvals | H3-08 pause/cancel/wait/replay and approval revocation services | Definition version, token, digest, receipt and policy reconciliation |
| Notifications | H3-09 cancellation, retry and in-app fallback controls | Intent key, attempt, preference and receipt reconciliation |
| Agent platform | H3-10 manifest/tool disable and orchestration cancellation | Manifest/tool/model version, delegation, budget, approval and receipt reconciliation |
| Platform hardening | H3-11 typed operator-action and recovery evidence service | Evidence digest, actor, expected version and audit chain |

## Incident sequence

1. Inspect the affected tenant-scoped boundary and establish correlation/evidence IDs.
2. Pause, quarantine, cancel, or disable through the authorized application command.
3. Preserve immutable failure, uncertain-outcome, audit, outbox, and receipt evidence.
4. Diagnose using redacted metrics, logs, traces, and versioned evaluation data.
5. Apply an approved forward fix or use authorized replay with unchanged identity.
6. Reconcile authoritative state, policy, idempotency, receipts, and checksums.
7. Resume only when authorization, SLO, recovery, and verification gates pass.

## SLO and escalation

Security, tenant-isolation, authorization, custody, deletion, approval, or agent-boundary
failures are critical/high and block release or resume. Missing samples fail an SLO;
they are not treated as success. Operational threshold misses remain paused until the
accountable platform owner records a verified recovery or an explicitly permitted,
time-bounded non-safety disposition.

## Backup, restore, export, closure, and deletion

Use the H1 recovery manifest extended through migration `0032_h3_platform_hardening`.
Restore into an isolated environment, verify tenant counts and digests, apply current
policy/revocation state, and run complete PostgreSQL/RLS and smoke checks before
promotion. Closure and deletion must reconcile every source and derivative or record
an explicit auditable exception. Destructive schema rollback after accepted evidence
uses a reviewed forward fix or export.
