# H3 Formal Security Review

**Owner:** Atlas Security Engineering

**Scope:** H3-01 through H3-11 reusable platform
**Decision:** No unresolved critical or high threat

## Threat-specific review

| Threat | Traceable mitigation evidence | Residual risk |
|---|---|---|
| Cross-workspace resource, search, workflow, agent, telemetry, or evidence access | Composite tenant keys, execution-context repositories, forced RLS and PostgreSQL attack tests | Low |
| Authorization or delegation amplification | H1 authorization, runtime revalidation, attenuating H3-10 delegation tests | Low |
| Approval/action-digest substitution | Immutable digest, expiry/revocation and changed-input workflow/agent tests | Low |
| Prompt injection or sensitive model egress | Classified cited context, secret rejection, private-route and injection fitness tests | Low |
| Arbitrary code, SQL, repository, or provider tool execution | Registered application command/query boundary and scope fitness | Low |
| Duplicate, reordered, replayed, or cancelled effect | H1 idempotency, H3 durable jobs, version preconditions and receipts | Low |
| Forged success or ambiguous provider outcome | Verified receipts and explicit uncertain outcome contracts | Low |
| Budget, model-policy, quota, or emergency-disable bypass | Fail-closed budget/risk policy, operator pause and disable tests | Low |
| Document substitution or derivative-lineage loss | Content hashes, immutable versions, custody, provenance and deletion-lineage tests | Low |
| Search authorization through vector similarity | SQL ACL predicates before retrieval and context assembly | Low |
| Audit or telemetry disclosure/tampering | Append-only audit, minimized typed telemetry, digests and sensitive-label rejection | Low |
| Backup/restore reactivates revoked authority or deleted state | Version/checksum reconciliation and recovery disposition controls | Low |
| H4, provider, connector, UI, or business-agent scope leakage | Architecture Fitness module/import/exclusion checks | Low |

## Residual-risk disposition

Remaining low risks concern workload growth, operational tuning, upstream availability,
and future model behavior. They require monitoring and maintenance but do not weaken
tenant isolation, authorization, custody, approval, audit, or agent boundaries. There
is no unresolved critical or high residual risk and no time-bounded risk acceptance is
required for Formal H3 Exit.
