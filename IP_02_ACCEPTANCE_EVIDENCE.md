# IP-02 Gmail OAuth Workspace Connection Acceptance Evidence

**Owner:** Atlas Platform Engineering
**Status:** Candidate; awaiting pull-request review and protected checks
**Accepted baseline:** `0032_h3_platform_hardening`
**Migration:** None; IP-02 reuses accepted H2 persistence

## Scope delivered

- Gmail-specific OAuth protocol composition behind the canonical H2 OAuth dispatcher
  port, with no provider type in the Integration Layer or business layer.
- Operation-driven minimum Gmail scopes: read-only, compose, and send are requested
  only for the approved email operations that need them.
- Incremental callback grants may include previously approved Google scopes, while the
  Gmail connection records and evaluates only its Gmail capability scope subset.
- Canonical state, S256 PKCE, issuer, redirect, expiry, replay, actor, session,
  membership, authorization-decision, and workspace binding.
- Offline and incremental authorization with a provider account verified through the
  Gmail profile boundary before encrypted persistence.
- Workspace-owned managed envelope credential generations with exact connection,
  provider, connection-kind, and Google-account consistency validation.
- Safe refresh into a new encrypted generation; missing, revoked, disabled, malformed,
  expired-without-refresh, or provider-failed authorization denies capability use.
- Minimal immutable audit/outbox evidence that contains no client secret, code, state,
  PKCE verifier, access token, refresh token, ciphertext, or provider payload.

## Canonical ownership and isolation

IP-02 adds no connection, credential, OAuth transaction, permission, audit, provider,
tenant, or routing model. It composes `app.connections`,
`app.connection_credentials`, `app.oauth_transactions`, `app.encryption`,
`app.authorization`, `app.execution_context`, `app.messaging`,
`app.email_capability`, and `app.integration_layer`.

Every lookup uses the canonical execution context and workspace-keyed repository.
PostgreSQL forced RLS remains unchanged. A Gmail grant is accepted only when its
verified Google account matches the workspace-owned connection's provider account.

## TDD and verification

- Contract tests cover scope minimization, authorization URL/PKCE construction,
  redaction, exchange failure, canonical transaction composition, refresh persistence,
  and fail-closed refresh.
- PostgreSQL acceptance covers encrypted credential persistence, capability ownership,
  account mismatch, immutable audit evidence, and cross-workspace denial.
- Architecture Fitness proves the no-migration baseline and rejects duplicate OAuth or
  credential infrastructure and future-provider scope.
- Final local and protected CI results are recorded in the pull request before review.

## Compatibility and exclusions

Phase 1 Gmail endpoints and legacy/shadow/canonical routing are unchanged. IP-02 adds
no Calendar, Drive, Contacts, WhatsApp, Stripe, LinkedIn, Facebook, Instagram, TikTok,
YouTube, X, CRM, UI, synchronization, webhook, business workflow, or business-agent
functionality. No real Gmail account connection is claimed by this evidence.

## Rollback

IP-02 adds no migration. Reverting its adapter composition and tests restores the
accepted IP-01/H2 behavior. Existing encrypted generations and audit evidence remain
governed by H2 recovery and cutover controls; disabling the IP-02 composition does not
delete or expose authorization material and creates no provider-side duplication.
