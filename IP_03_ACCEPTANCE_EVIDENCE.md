# IP-03 Operator-facing Gmail Connection Lifecycle Acceptance Evidence

**Owner:** Atlas Platform Engineering
**Status:** Implementation candidate; pending pull-request review and protected checks
**Accepted baseline:** `0032_h3_platform_hardening`
**Migration:** None; IP-03 composes accepted H2/IP-01/IP-02 persistence

## Scope delivered

- Authenticated operator initiation for an explicitly selected workspace using the
  canonical opaque identity session, active membership, execution context, CSRF, and
  H1 authorization boundaries.
- Creation of, or reauthorization for, one canonical workspace-owned Google Workspace
  connection with operation-driven Gmail capability grants and minimum Gmail scopes.
- Callback completion through the accepted H2/IP-02 state, S256 PKCE, issuer,
  redirect, expiry, replay, actor, session, membership, workspace, scope, provider,
  and Google-account binding controls.
- A workspace-scoped lifecycle query with deterministic `initiated`,
  `authorization_pending`, `active`, `revoked`, `disabled`, `expired`, `invalid`, and
  `mismatched` states.
- A deliberately non-secret response containing only connection/workspace identifiers,
  provider display identity, lifecycle state, granted scopes, and timestamps.
- Immutable audit evidence for lifecycle reads; accepted connection and OAuth services
  continue to own initiation, completion, credential-generation, and outbox evidence.

## Canonical reuse and isolation

IP-03 introduces no connection, OAuth transaction, credential, account, permission,
tenant, encryption, audit, or provider model. It composes the accepted
`app.connections`, `app.oauth_transactions`, `app.connection_credentials`,
`app.encryption`, `app.authorization`, `app.identity`, `app.memberships`,
`app.execution_context`, and `app.messaging` boundaries.

Every operator request resolves exactly one workspace from either the authenticated
path or the signed OAuth state hint before applying the canonical execution context.
Repository filtering and PostgreSQL forced RLS remain authoritative. A returned Google
account must match the account declared by that workspace-owned connection before any
encrypted credential generation can become active.

## Security and redaction

The operator response cannot serialize an access token, refresh token, client secret,
authorization code, OAuth state, PKCE verifier, ciphertext, decrypted credential, or
raw provider payload. Authentication and authorization errors are translated to safe,
deterministic responses. Callback errors never echo provider or credential material.

Existing IP-02 refresh and rotation behavior remains canonical: an expired grant is
refreshed through the provider boundary into a new encrypted generation, the previous
generation is revoked, and missing, malformed, disabled, revoked, or failed credentials
deny use and require reauthorization.

## TDD and verification

- New contract tests cover all lifecycle states, response redaction, bounded operator
  routes, and Phase 1 Gmail route compatibility.
- New PostgreSQL acceptance covers authenticated session/membership context, multiple
  workspaces, cross-workspace denial, forced RLS behavior, and immutable state-read
  audit evidence.
- Architecture Fitness proves canonical reuse, the no-migration baseline, secret
  redaction, and exclusion of later providers and business-agent scope.
- New IP-03 tests: **10** (five contract, one PostgreSQL/RLS, and four Architecture
  Fitness tests).
- Complete PostgreSQL-backed Architecture Fitness: **329 passed**.
- Complete non-architecture regression suite: **332 passed** with the existing single
  Starlette/httpx deprecation warning.
- Ruff passed for the complete Architecture Fitness suite and every changed Python
  file. Production Docker build, application smoke, and durable-worker smoke passed.
- Protected GitHub checks remain required before this candidate can be accepted.

## Compatibility and exclusions

Phase 1 Gmail endpoints and accepted H2 legacy, shadow, and canonical routing remain
unchanged. IP-03 adds no Calendar, Drive, Contacts, WhatsApp, Stripe, LinkedIn,
Facebook, Instagram, TikTok, YouTube, X, CRM, UI/product work, synchronization,
webhook, workflow, mailbox operation, or business-agent functionality. No live Gmail
authorization is claimed by this evidence.

## Rollback

IP-03 adds no migration. Reverting the new operator router and composition service
restores accepted IP-02 behavior without deleting or rewriting connections,
transactions, encrypted credential generations, audit evidence, or provider state.
