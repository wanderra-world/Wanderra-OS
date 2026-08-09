# ADR-036 Initial Google Identity Bootstrap Evidence

**Owner:** Atlas Platform Engineering

**Status:** Executed once; bootstrap disabled; repository verification complete

**Governing decisions:** ADR-023, ADR-035, ADR-036

**Accepted migration baseline:** `0032_h3_platform_hardening`

**Migration:** None

## Fixed target

- Canonical user: `d34c44c9-1ada-43ad-ad70-5ae9568df146`
- Workspace: `874fc276-27be-557d-cd2c-179bed466907`
- Required membership: active `workspace_owner@1`
- Required issuer after verification: `https://accounts.google.com`
- Verified subject fingerprint:
  `4b1ae023cab65d99cad4fe406ea9a7eb7dce2954d868fe026f8097fbee4073d6`
- Email was not used as a lookup or binding key.

## Approval state

Preparation was explicitly approved on August 9, 2026. The real Google OIDC proof
normalized the issuer and produced the immutable subject represented by the
fingerprint above. A second approval named that exact issuer and subject for the fixed
canonical user and workspace before persistence.

The atomic commit created:

- External identity link: `ce24da2a-653d-4a26-8c38-b6edd323a58c`
- Immutable audit event: `d60bc81f-6948-4792-b23f-e905cf86fe1f`
- Approval reference: `ADR-036-BOOTSTRAP-2026-08-09-02`

The ceremony issued no Atlas session. The ID token, authorization code, PKCE verifier,
state, nonce, client secret, and provider tokens were not persisted or audited.

## Verification evidence

- Google issuer, audience, signature, expiry, issued-at, nonce, state, PKCE, and
  single-use callback verification completed through the accepted ADR-035 adapter.
- Exactly one active link and one immutable audit event exist; the workspace audit
  chain verifies successfully.
- A replay invocation failed before OAuth because the bootstrap is disabled.
- After the ceremony terminated, the ordinary ADR-035 browser callback resolved the
  accepted link and independently issued one active OIDC-strength workspace session.
  Successful `identity.operator_authenticated` and `identity.session_issued` audit
  events distinguish that normal login from the ceremony, which issued no session.
- Migration remains `0032_h3_platform_hardening`; no schema change was introduced.
- ADR-036 slice tests: 9 passed, including rollback, non-repeatability, audit-chain,
  and immutability evidence.
- Architecture Fitness: 336 passed after execution.
- Regression suite: 355 passed after execution with the existing single
  Starlette/httpx deprecation warning.
- Ruff, Docker build, application smoke, and durable-worker smoke passed.
- Final post-execution verification confirmed the one-link invariant, valid audit
  chain, zero ceremony-issued sessions, disabled replay, and unchanged migration
  baseline.
