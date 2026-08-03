# H3-10 Agent Platform Contracts Acceptance Evidence

**Owner:** Atlas Platform Engineering

**Status:** Accepted and merged through PR #44

**Governing specification:** `H3_ARCHITECTURE.md` H3-10 and
`H3_IMPLEMENTATION_GUIDE.md` sections 1.61–1.68

**Migration:** accepted `0031_h3_agent_platform`, additive from accepted
`0030_h3_notification_center`

## Scope delivered

- Immutable, versioned, workspace-owned agent manifests and provider-neutral tool
  registrations mapped only to typed application command/query references.
- Typed model and executor ports; inert evidence-linked plan proposals; deterministic
  validation; immutable action digests; and explicit verified, failed, or uncertain
  execution outcomes.
- Attenuating, expiring delegation contracts; execution-time canonical authorization;
  digest-bound approval requirements for high/critical risk; and fail-closed risk,
  classification, schema, registration, and emergency-disable controls.
- Deterministic token, cost, tool-call, and elapsed-time budgets with transaction-safe,
  idempotent reservation evidence.
- Durable orchestration, multi-step progression, cancellation, receipts, audit/outbox
  evidence, synthetic conformance evaluations, and activation gating.
- Eleven additive PostgreSQL tables with composite tenant keys, relationship foreign
  keys, forced RLS, empty-state downgrade, and populated-state forward-fix protection.

## Explicit exclusions

No business agent, business prompt, autonomous goal, provider SDK/tool, connector,
external integration, UI, direct SQL/repository/shell/Python tool, multi-agent social
protocol, H3-11, H4, or later roadmap functionality is included.

## TDD and security evidence

- Red: contract and architecture tests initially failed because `app.agent_platform`
  did not exist.
- Green: typed contracts, persistence, repository/service boundaries, migration,
  authorization/approval/budget enforcement, orchestration, evaluation, and evidence
  made the focused suite pass.
- Tool confinement rejects unregistered, disabled, provider-specific, arbitrary-code,
  and schema/risk-mismatched tools before execution.
- Delegation cannot amplify permission, risk, or expiry. Authorization, active
  manifest/tool state, delegation, resource version, action digest, approval, and
  budget are revalidated at execution.
- Sensitive credential-like plan input fails closed. Results that cannot be verified
  remain explicitly uncertain and are never promoted to success.
- Real PostgreSQL 16/pgvector rehearsal validates all eleven tables, enabled/forced
  RLS, empty downgrade/re-upgrade, and guarded populated downgrade.

## Verification results

- New H3-10 tests: **11 passed** (7 deterministic contract tests, 2 Architecture
  Fitness tests, and 2 real PostgreSQL/RLS/migration tests).
- Complete clean repository suite: **609 passed**, with the existing single
  Starlette/httpx deprecation warning.
- Complete Architecture Fitness: **313 passed**.
- Ruff for the complete Architecture Fitness suite and every H3-10 production,
  migration, test, and model-registry file: **passed**.
- Alembic: accepted single head `0031_h3_agent_platform`; upgrade, empty
  downgrade/re-upgrade, forced RLS, and populated downgrade refusal passed.
- Production Docker image `atlas-h3-10`: **built successfully**.
- Production application import smoke and durable-worker smoke: **passed**.
- PR #44: protected Architecture Fitness, Regression Tests, Docker Build and Smoke,
  and aggregate H0 Required Gate checks passed.

## Compatibility and rollback

Migration `0031_h3_agent_platform` is additive and rewrites no accepted H0–H3-09
state. Empty-state schema downgrade is supported. Once agent-platform or associated
audit/outbox evidence exists, destructive schema rollback fails closed and requires a
reviewed forward fix or export. Application rollback disables manifests, tools, model
planning, and orchestration while retaining authorized inspection, cancellation, and
immutable evidence.

## Slice isolation

Only H3-10 Agent Platform Contracts were implemented by PR #44 at `a44af1b`. H3-11 is
authorized exclusively by the governance controls owned by
`H3_IMPLEMENTATION_GUIDE.md` sections 1.69–1.76. H4, UI, provider-specific
integrations, connectors, external integrations, and business agents remain
unauthorized and unimplemented.
