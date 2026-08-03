# H3 Evaluation Report

**Owner:** Atlas Platform Evaluation
**Dataset:** `synthetic.h3-exit.v1`

## Evaluated boundaries

| Area | Reproducible evaluation | Result |
|---|---|---|
| Search | Exact/structured Recall@10, hybrid NDCG@10, ACL-first retrieval and latency fixtures | Meets accepted H3-06 thresholds |
| Prompt injection | Untrusted context, secret-like input, instruction and model-egress rejection tests | Pass |
| Planning | Typed evidence-linked inert plan validation and changed-binding rejection | Pass |
| Tool selection | Registered enabled application command/query confinement | Pass |
| Delegation/approval | Attenuation, expiry, risk ceiling, digest and runtime authorization checks | Pass |
| Outcomes | Verified, failed and explicitly uncertain receipts | Pass |
| Reliability | Crash, lease expiry, retry, duplicate, cancellation and replay suites | Pass |
| Cost/budgets | Token, cost, tool-call and duration ceilings fail closed | Pass |
| Tenant isolation | PostgreSQL forced RLS and cross-workspace adversarial suites | Pass |
| Provider neutrality | Shared synthetic multi-provider H2 conformance and H3 import fitness | Pass |

## Release disposition

The versioned synthetic evaluation contains no business agent or live provider action.
It records zero critical findings and zero high findings. Latency, reliability, search
quality, planning, tool selection, outcome verification, and cost controls satisfy the
approved release boundaries. Formal acceptance remains pending protected CI and merge.
