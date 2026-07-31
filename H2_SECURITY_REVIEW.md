# H2 Formal Security Review

**Owner:** Atlas Security Engineering  
**Scope:** Accepted H2-01 through H2-10 provider migration foundation  
**Date:** 31 July 2026

## Review outcome

The threat-specific review found no unresolved critical or high-severity finding.
The controls below are backed by committed negative-path, PostgreSQL, RLS,
architecture, and regression tests. No risk acceptance is required for a critical or
high finding.

| Threat | Mitigation evidence | Residual risk |
|---|---|---|
| Cross-workspace connection or mirror access | Execution-context binding, composite tenant keys, forced RLS, cross-workspace PostgreSQL tests | Low |
| Credential disclosure in storage, logs, audit, events, or errors | Managed envelope encryption, opaque references, redaction and architecture fitness checks | Low |
| Credential substitution or use after disable/revocation | Connection/workspace binding, lifecycle checks before gateway construction, negative-path tests | Low |
| OAuth state theft, replay, expiry, or scope confusion | Hashed state, PKCE, one-time consume, expiry, redirect and connection binding | Low |
| Revoked membership or denied action reaches a provider | Authorization precedes credential resolution and routing; service negative-path tests | Low |
| Unapproved external mutation | Action-specific approval verification before provider invocation | Low |
| Duplicate provider effects | Caller-owned idempotency keys, replay fingerprints, transactional evidence, read-back verification | Low |
| Blind or stale mutation | Required canonical version preconditions and conflict mapping | Low |
| Shadow mode performs a mutation | Read-only shadow route; routing tests assert a single authoritative mutation | Low |
| Shadow mismatch is ignored during cutover | Immutable comparison evidence and configured sample/failure thresholds | Low |
| Cutover strands credentials or loses data | Legacy fallback retained, independent route flags, tested rollback and reauthorization exception | Low |
| Provider payload or SDK escapes adapter boundary | Namespaced extensions, canonical DTOs/errors, import fitness tests | Low |
| Export, recovery, or closure omits H2 state | Complete H2 table manifest and recovery/export/closure tests | Low |
| Lossy schema rollback destroys accepted evidence | Additive revisions and guarded downgrade/forward-fix rules | Low |
| Provider deletion is mistaken for tenant closure | Closure preserves provider-reconciliation boundary; deletion remains explicitly provider-side | Low |

## Residual-risk disposition

Low operational risks remain around upstream provider availability, quota behavior,
and live-provider drift. They are controlled by canonical transient errors,
idempotent retry contracts, legacy rollback during H2 compatibility, observability,
and provider-specific adapter tests. These risks do not weaken tenant isolation,
credential custody, approval, or audit guarantees.

The review confirms that no unresolved critical or high security threat remains and
that H3 has not been started.
