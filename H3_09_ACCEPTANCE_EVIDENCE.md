# H3-09 Notification Center Acceptance Evidence

**Owner:** Atlas Platform Engineering

**Status:** Implementation complete; awaiting pull-request review and merge

**Governing specification:** `H3_ARCHITECTURE.md` H3-09 and
`H3_IMPLEMENTATION_GUIDE.md` sections 1.53–1.60

**Migration:** `0030_h3_notification_center`, additive from accepted
`0029_h3_workflow_approval`

## Scope delivered

- Canonical workspace-owned notification intents with caller-owned intent and
  deduplication keys, normalized input digests, source lineage, classification,
  policy version, destination reference, and deterministic delivery eligibility.
- Immutable provider-neutral template versions with an allowlisted variable surface,
  inert formatting, size limits, and explicit rejection of executable syntax and
  credential-like content.
- Workspace/user/channel preferences with opt-out, classification ceilings, IANA
  timezone quiet periods, digest configuration, and deterministic DST-aware deferral.
- Provider-neutral channel capability and delivery port contracts with typed retry,
  bounce, failure, cancellation, uncertainty, and verified-receipt outcomes.
- Durable attempt, receipt, digest, failure-state, and canonical in-app inbox
  persistence with execution-context-bound repository and service boundaries.
- Atomic audit and transactional outbox evidence for accepted notification intents.
- Eight new workspace-owned PostgreSQL tables with composite tenant keys, forced RLS,
  empty-state downgrade, and populated-state forward-fix protection.

## Explicit exclusions

No provider adapter, connector, provider SDK, external integration, marketing
campaign, business-specific template, workflow business policy, UI, agent, planner,
orchestrator, H3-10+, H4, or business-agent behavior is included.

## TDD and verification evidence

- Red: contract tests initially failed because `app.notifications` did not exist.
- Green: deterministic contracts, persistence, repository/service boundaries,
  migration, audit/outbox evidence, and in-app fallback made the focused suite pass.
- PostgreSQL: real pgvector/PostgreSQL 16 rehearsal validates all eight tables,
  enabled and forced RLS, empty downgrade/re-upgrade, and guarded populated downgrade.
- Security: authorization, opt-out, destination eligibility, classification, secret
  minimization, deduplication digest, and verified receipt paths fail closed.
- Recovery: delivery workers can stop while accepted intents remain durable and the
  canonical in-app inbox remains independently available.
- Architecture Fitness: provider-neutral boundaries and H3-10+ exclusions are
  executable.

## Verification results

- New H3-09 tests: **10 passed** (8 deterministic contract/Architecture Fitness tests
  and 2 real PostgreSQL/RLS/migration tests).
- Complete clean repository suite: **597 passed**, with the existing single
  Starlette/httpx deprecation warning.
- Complete tracked Architecture Fitness: **308 passed**.
- Ruff for Architecture Fitness and every H3-09 production, migration, test, and model
  registry file: **passed**.
- Alembic: single head `0030_h3_notification_center`; upgrade, empty
  downgrade/re-upgrade, forced RLS, and populated downgrade refusal passed on
  pgvector/PostgreSQL 16.
- Production Docker image `atlas-h3-09`: **built successfully**.
- Production application import smoke and durable-worker smoke: **passed**.
- Protected GitHub results are recorded on the dedicated pull request before merge.

## Compatibility and rollback

The migration is additive and rewrites no accepted H0–H3-08 data. Empty-state schema
downgrade is supported. Once notification state exists, destructive downgrade fails
closed with the required reviewed-forward-fix/export instruction. Application rollback
disables external delivery while preserving authorized inspection, cancellation,
export, and in-app access.

## Slice isolation

H3-10, H3-11, H4, UI, providers, connectors, external integrations, and business
agents remain unauthorized and unimplemented.
