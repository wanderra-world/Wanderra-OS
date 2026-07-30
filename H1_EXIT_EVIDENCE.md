# H1 Formal Exit Evidence

**Owner:** Atlas Engineering  
**Status:** Accepted
**Governing specification:** `H1_PLATFORM_SPEC.md`, H1-10  
**H2 status: Not started**

This document records acceptance evidence. It does not change the architecture,
ADRs, roadmap, production schema, or accepted H1 slice contracts.

## Evidence matrix

| Exit criterion | Evidence | Result |
|---|---|---|
| Synthetic tenant isolation | Two independent synthetic organizations and workspaces; adversarial application-context and PostgreSQL RLS probes | Accepted |
| Session revocation | Real session issuance, revocation, authentication rejection, and authorization rejection | Accepted |
| Authorization | Fixed-role allow path and cross-workspace deterministic deny path | Accepted |
| Audit integrity | Real command and closure audit records plus PostgreSQL audit-chain verification | Accepted |
| Event idempotency and concurrency | Command replay returns the original result; the complete H1-08 concurrency suite remains merge-blocking | Accepted |
| Backup and isolated restore | Managed-key encrypted snapshot, authenticated restore, manifest comparison, and RPO/RTO assertions; H1-09 retains physical isolated-database restoration evidence | Accepted |
| Workspace closure and deletion | Authorized closure freezes writes, revokes access, erases eligible H1 derivatives, preserves evidence, and emits one closure event | Accepted |
| Repository context enforcement | Mismatched transaction/repository context is rejected and PostgreSQL RLS exposes only the selected workspace | Accepted |
| Phase 1 compatibility | Complete regression suite includes Gmail, Calendar, Drive, memory, and existing API tests | Accepted |
| Migration safety | H1-10 adds no schema; repeated upgrade to accepted head `0013_h1_recovery_closure` succeeds | Accepted |
| Docker | Production image build and application smoke import | Accepted |
| Architecture Fitness | Complete architecture suite, including H1-10 scope checks | Accepted |

## Security review

The H1 security acceptance surface is workspace isolation, identity and session
lifecycle, deterministic authorization, execution-context propagation, envelope
encryption, immutable audit, transactional messaging, recovery, and closure.

| Finding class | Review result |
|---|---|
| Critical | None unresolved |
| High | None unresolved |
| Medium | No new H1-10 finding; existing architectural limitations remain governed by their approved later-stage owners |
| Low | No new H1-10 finding |

No risk acceptance is used to waive a critical or high finding. Provider-owned data
reconciliation remains explicitly assigned to H2 and is not represented as completed
by H1 closure.

## Scope confirmation

- Provider migration: Not performed.
- No universal entity, memory, search, agent, provider adapter, or H2 implementation
  is included.
- No architecture, ADR, roadmap, or accepted-slice contract is modified.
- No production migration is required because H1-10 is an integrated evidence and
  defect-remediation slice.

## Formal H1 Exit

**Formal H1 Exit is accepted.** Pull request #11 is merged, the complete local
verification succeeded, and Architecture Fitness, Regression Tests, Docker Build and
Smoke, and the required GitHub gate passed. H2 remains unstarted and requires separate
authorization.
