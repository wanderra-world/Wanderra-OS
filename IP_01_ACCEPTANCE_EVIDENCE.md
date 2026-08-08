# IP-01 Provider-Neutral Integration Layer Foundation Acceptance Evidence

**Owner:** Atlas Platform Engineering  
**Status:** Accepted and merged through PR #48 at `4bee069`
**Accepted baseline:** `0032_h3_platform_hardening`  
**Migration:** None; IP-01 composes accepted H2 persistence

## Scope delivered

- One provider-neutral, workspace-aware application resolver over canonical H2
  connection, capability, credential, authorization, execution-context, and audit
  boundaries.
- Fail-closed authorization before repository access.
- Active connection, granted capability version, registered operation, usable managed
  credential metadata, provider/account consistency, and required-scope validation.
- Inert resolution metadata containing no secret, token, ciphertext, provider payload,
  SDK client, or decrypted credential.
- Immutable `integration.resolved` audit evidence correlated to the canonical request,
  actor, authorization decision, workspace, and connection.

## H2 canonical ownership map

| IP-01 concept | Reused canonical owner |
|---|---|
| Workspace, organization, actor, correlation | `app.execution_context` |
| Integration and provider account | `app.connections.Connection` |
| Provider and capability definitions | `app.connections` and `app.provider_capabilities` |
| Account authorization metadata | `app.connection_credentials.ConnectionCredential` |
| Encrypted secret custody | `app.encryption` through the existing credential envelope reference |
| Permission decision | `app.authorization` through `H1ConnectionAuthorizer` |
| Immutable evidence | `app.messaging.AuditWriterService` |
| Tenant isolation | Existing composite tenant keys and forced PostgreSQL RLS |

IP-01 introduces no parallel integration, provider, account, credential, OAuth,
permission, audit, or routing model.

## TDD and verification

- Red: contract tests failed because `app.integration_layer` did not exist.
- Green: **16 new IP-01 tests passed**: provider-neutral resolver unit and negative
  paths, Architecture Fitness, and real PostgreSQL workspace/RLS/audit evidence.
- Complete PostgreSQL-backed Architecture Fitness: **320 passed**.
- Complete non-architecture regression suite: **316 passed** with the existing single
  Starlette/httpx deprecation warning.
- Ruff for Architecture Fitness and every IP-01 production/test file: **passed**.
- Alembic remains at the accepted single head `0032_h3_platform_hardening`.
- Production Docker build, application smoke, and durable-worker smoke: **passed**.
- GitHub Architecture Fitness, Regression Tests, Docker Build and Smoke, and H0
  Required Gate: **passed** before PR #48 merged into protected `master`.

## Security and compatibility

Authorization runs before integration lookup. Every repository read is bound to the
canonical execution context and workspace. A missing, cross-workspace, inactive,
revoked, disabled, mismatched, ungranted, unsupported, or under-scoped boundary fails
before adapter construction. IP-01 never decrypts credentials and records no sensitive
payload in audit evidence. Existing H0-H3 and Phase 1 behavior is unchanged.

## Slice isolation

No provider adapter, Gmail OAuth flow, external network call, synchronization,
webhook, UI, business agent, business workflow, social integration, CRM, or future
Integration Platform slice is implemented.

## Rollback

IP-01 adds no schema or persisted aggregate. Reverting the isolated application module
and its tests restores the accepted H2 composition without credential, provider-state,
audit-history, or migration loss.
