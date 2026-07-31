# H2-05 Acceptance Evidence

Evidence for the canonical capability contracts and provider SDK boundary.

**Owner:** Atlas Core  
**Status:** Implementation complete; pending pull-request acceptance and merge  
**Governing specification:** [H2_PLATFORM_SPEC.md](H2_PLATFORM_SPEC.md#h2-05-canonical-capability-contracts-and-provider-sdk-boundary)  
**Architecture decisions:** ADR-002, ADR-004, ADR-020, ADR-026, ADR-031  
**Baseline:** H2-04 merge commit `254e516`

## Scope delivered

- Immutable versioned canonical email, calendar, and storage DTOs.
- Provider-neutral asynchronous capability ports.
- Deterministic provider capability discovery and exact-version negotiation.
- Stable canonical error taxonomy and retry classification.
- Opaque pagination cursors, timezone/offset-preserving timestamps, version
  preconditions, mutation idempotency contexts, and namespaced non-authoritative
  extension envelopes.
- A narrow SDK boundary that prevents concrete provider clients, resources, and
  exceptions from escaping adapters.
- A deterministic in-memory second-provider adapter and shared conformance tests.
- Static fitness checks for SDK leakage, provider-name branching, runtime coupling,
  and H2-06+ concepts.

## Explicit exclusions

- No production provider adapter or provider SDK invocation.
- No Gmail, Calendar, or Drive routing change.
- No Phase 1 API, service, credential, OAuth, mirror, or persistence change.
- No synchronization, shadow read, cutover, webhook, polling, scheduler, or worker.
- No universal entities or H2-06+ implementation.

## Phase 1 compatibility map

| Existing capability | Canonical H2-05 contract |
|---|---|
| Gmail profile | `EmailPort.profile` |
| Gmail recent/unread/search | `list_messages`, `list_unread`, `search_messages` |
| Gmail draft/send | `create_draft`, `send_message` with mutation idempotency |
| Calendar event list | `CalendarPort.list_events` |
| Calendar create/update/delete | mutation methods with idempotency and optional version preconditions |
| Drive list/search | `StoragePort.list_objects`, `search_objects` |
| Drive metadata/download/text | `read_metadata`, `download`, `read_text` |
| Drive upload | `upload` with canonical content metadata and idempotency |
| Drive metadata/content update | `update_metadata`, `update_content` with version preconditions |
| Drive delete | `delete` with version precondition and idempotency |

The contracts preserve stable external IDs, provider versions, offset-aware timestamps,
binary content, MIME/media types, and current Phase 1 fields without importing or
embedding provider SDK types.

## Security and failure evidence

- Canonical errors cover authentication, authorization, scope, rate limit, transient,
  conflict, not found, invalid input, quota, and unsupported capability.
- Retry behavior is deterministic: refresh authentication, refresh resource, bounded
  backoff, or never retry.
- Provider diagnostics and raw payloads have no field in canonical errors or DTOs.
- Mutation replay with identical input returns the recorded result; changed input under
  the same idempotency key fails closed.
- Stale mutations require version preconditions in the conformance adapter and return a
  canonical conflict.
- Extension keys must be namespaced and values JSON-compatible. Extensions remain
  non-authoritative and cannot change tenancy, authorization, audit, or conflict rules.
- Static tests prohibit provider SDK, database, framework, and production integration
  imports in the canonical module.

## Schema, migration, RLS, and rollback

H2-05 is deliberately schema-free. It defines immutable Python contracts, ports,
registry behavior, and test infrastructure only. Production remains at revision
`0017_h2_provider_mirrors`; no tenant-owned table or repository is introduced, so no
new RLS policy is applicable.

Rollback is application-only: remove the isolated `app/provider_capabilities` module
and its tests. No database or provider state exists to migrate, reverse, or reconcile.
Migration rehearsal verifies the accepted `0017` head remains upgradeable,
downgradeable on an empty H2-04 state, and re-upgradeable.

## Reproducible tests

- Contract and serialization:
  [tests/provider_capabilities/test_h2_05_contracts.py](tests/provider_capabilities/test_h2_05_contracts.py)
- Shared second-provider conformance:
  [tests/provider_capabilities/test_h2_05_conformance.py](tests/provider_capabilities/test_h2_05_conformance.py)
- Architecture boundary:
  [tests/architecture/test_h2_05_capability_scope.py](tests/architecture/test_h2_05_capability_scope.py)

## Verification results

```text
Focused H2-05 contracts, conformance, and slice isolation
24 passed

Architecture Fitness with PostgreSQL/RLS
263 passed

Complete non-architecture regression suite
165 passed, 1 accepted Starlette/httpx deprecation warning

Changed-scope and mandatory Architecture Fitness Ruff
All checks passed

Migration rehearsal
empty upgrade -> 0017; downgrade -> 0016; re-upgrade -> 0017 passed

Production Docker build
atlas-h2-05 built successfully

Production image smoke
FastAPI application, capability registry, and SDK boundary imported successfully
```

The complete local inventory is **428 passing tests**. A repository-wide Ruff
diagnostic continues to report 102 pre-existing Phase 1 formatting findings outside
this slice; H2-05 adds no finding. The merge-blocking Architecture Fitness Ruff scope
and every changed H2-05 file pass.

Protected GitHub results are recorded after the dedicated pull request is verified.

## Findings

- No critical or high H2-05 finding is open.
- The existing Phase 1 Starlette/httpx deprecation warning remains unrelated.
- H2-06 has not started.
