# Google Operator Authentication Runtime Acceptance Evidence

**Owner:** Atlas Platform Engineering

**Status:** Accepted and merged through PR #54 at `37614bb`

**Governing decision:** ADR-035

**Accepted migration baseline:** `0032_h3_platform_hardening`

**Migration:** None

## Bounded capability

- Google Identity is the initial trusted external authentication adapter using OIDC
  Authorization Code Flow with S256 PKCE and identity-only `openid email profile`
  scopes.
- A short-lived authenticated transaction cookie binds state, nonce, PKCE verifier,
  expiry, and explicitly selected workspace. Google consumes the authorization code
  once, and the callback deletes the transaction cookie.
- Google ID-token signature, audience, issuer, expiry, issued-at time, nonce, and
  verified-email evidence are validated before Atlas identity resolution.
- The verified issuer/subject resolves only an existing active
  `ExternalIdentityLink` and active canonical `User`. Email is never a lookup, account
  creation, merge, or workspace-authority key.
- The explicitly selected active workspace, active membership, and deny-first fixed
  `manage_workspace` permission are verified before the existing
  `IdentityLifecycleService` issues a workspace-scoped OIDC session.
- Session and CSRF values are carried by `Secure`, `HttpOnly`, `SameSite=Lax`,
  `__Host-` cookies; neither value is serialized in the response body. Session
  revocation deletes all operator cookies.
- Authenticated Gmail connection revoke and emergency-disable operations atomically
  use the accepted connection, encrypted credential, authorization, audit/outbox, and
  forced-RLS services.

## Security and compatibility

Operator authentication and Gmail capability authorization remain separate OAuth
transactions, scopes, credentials, and revocation lifecycles. No Gmail access token,
refresh token, authorization code, ID token, state, nonce, PKCE verifier, session
secret, CSRF value, client secret, ciphertext, or decrypted credential appears in an
API response model or audit payload.

The implementation adds no password, self-registration, automatic identity linking,
local authentication fallback, alternate user model, alternate session model, schema,
migration, UI, IP-04 capability, provider expansion, mailbox expansion, workflow, or
business-agent behavior. Accepted IP-02/IP-03 Gmail OAuth semantics and Phase 1 routes
remain unchanged.

## Verification evidence

- New tests: **21** across Google OIDC, provider-neutral identity mapping, secure
  cookies/API boundaries, connection lifecycle, PostgreSQL/RLS, and Architecture
  Fitness.
- Focused changed-scope verification: **26 passed** with the repository's existing
  Starlette/httpx deprecation warning.
- Complete PostgreSQL-backed Architecture Fitness: **333 passed**.
- Complete non-architecture regression suite: **349 passed** with the existing single
  Starlette/httpx deprecation warning.
- PostgreSQL/RLS identity-to-session and cross-workspace evidence: **1 passed** against
  migration `0032_h3_platform_hardening`.
- Ruff passed for the complete Architecture Fitness suite and every changed Python
  file.
- Production Docker image `atlas-adr035-ci` built successfully; application import
  smoke and durable-worker smoke passed.
- PR #54 passed all required protected GitHub checks and merged into `master`.

## Live operational verification

After the separately approved ADR-036 ceremony established the initial immutable
issuer/subject link, an ordinary ADR-035 browser callback resolved that existing link,
verified the selected workspace membership and authorization, and issued one active
OIDC-strength workspace session. Immutable audit evidence records successful
`identity.operator_authenticated` and `identity.session_issued` actions. The bootstrap
issued no session and is permanently disabled. No secret or immutable subject value
is recorded in this evidence.

## Rollback

The slice is additive at the application layer and introduces no durable schema.
Reverting the operator-authentication router, Google Identity adapter, canonical
composition service, and Gmail availability endpoints restores the accepted IP-03
baseline without rewriting users, identity links, memberships, sessions, connections,
encrypted credentials, or audit evidence.
