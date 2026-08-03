# H3 Evidence Matrix

**Owner:** Atlas Platform Engineering

**Baseline:** H3-01 through H3-10 accepted; H3-11 candidate
**Governing exit contract:** [H3_EXIT_DEFINITION.md](H3_EXIT_DEFINITION.md)

## Slice traceability

| Slice | Accepted capability | Primary evidence |
|---|---|---|
| H3-01 | Resource Graph | `H3_01_ACCEPTANCE_EVIDENCE.md`, `tests/resource_graph/` |
| H3-02 | Durable execution and scheduler | `H3_02_ACCEPTANCE_EVIDENCE.md`, `tests/jobs/` |
| H3-03 | Document custody and derivation | `H3_03_ACCEPTANCE_EVIDENCE.md`, `tests/documents/` |
| H3-04 | Knowledge and Timeline | `H3_04_ACCEPTANCE_EVIDENCE.md`, `tests/knowledge/` |
| H3-05 | Governed Memory Manager | `H3_05_ACCEPTANCE_EVIDENCE.md`, `tests/memory/` |
| H3-06 | Search and context assembly | `H3_06_ACCEPTANCE_EVIDENCE.md`, `tests/search_context/` |
| H3-07 | Task Manager | `H3_07_ACCEPTANCE_EVIDENCE.md`, `tests/tasks/` |
| H3-08 | Workflow and Approval Engine | `H3_08_ACCEPTANCE_EVIDENCE.md`, `tests/workflows/` |
| H3-09 | Notification Center | `H3_09_ACCEPTANCE_EVIDENCE.md`, `tests/notifications/` |
| H3-10 | Agent platform contracts | `H3_10_ACCEPTANCE_EVIDENCE.md`, `tests/agent_platform/` |
| H3-11 | Platform hardening and Formal H3 Exit | `H3_11_ACCEPTANCE_EVIDENCE.md`, `tests/platform_hardening/`, `tests/architecture/test_h3_11_scope.py` |

## Exit-gate traceability

| Gate | Reproducible evidence | Disposition |
|---|---|---|
| Gate A — baseline and closure | Accepted slice evidence, protected merge commits, H3-11 scope fitness | Pass pending H3-11 merge |
| Gate B — workspace/security | PostgreSQL suites, forced-RLS migration checks, `H3_SECURITY_REVIEW.md` | Pass |
| Gate C — resources/data planes | Resource, document, knowledge, memory, timeline, search suites | Pass |
| Gate D — durable execution | Job crash/replay/scheduler tests and durable-worker smoke | Pass |
| Gate E — derivative governance | Document custody and deletion-lineage tests | Pass |
| Gate F — AI safety | Search quality, ACL, context, memory, injection, and egress tests | Pass |
| Gate G — tasks/workflows/notifications | H3-07 through H3-09 contract and PostgreSQL suites | Pass |
| Gate H — agent readiness | H3-10 contract, approval, budget, receipt, migration, and RLS tests | Pass |
| Gate I — provider neutrality | H2 conformance/compatibility suite and H3 Architecture Fitness | Pass |
| Gate J — operations | H3-02 controls plus `H3_OPERATIONS_RUNBOOK.md` and H3-11 telemetry, evaluation, recovery, and operator evidence | Pass |
| Gate K — engineering fitness | Full regression, Architecture Fitness, Ruff, Docker, smoke, migration and CI | Pass pending protected CI |

Formal acceptance is not effective until the H3-11 PR passes protected checks and is
merged into `origin/master`.
