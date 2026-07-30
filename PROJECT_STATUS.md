# Atlas Platform Status

**Owner:** Atlas Platform Engineering

Last updated: 30 July 2026

## Summary

Atlas is the AI assistant layer of Wanderra OS. The current platform is a Python 3.12
FastAPI service backed by PostgreSQL, with OpenAI-powered chat and durable memory plus
working Google integrations for Gmail, Calendar, and Drive.

The local Docker deployment is operational. Database migrations are at
`0011_h1_envelopes`. Formal H0 Exit and H1-01 through H1-06 are accepted. H1-07 adds
managed per-record envelope encryption and additive credential shadow metadata
without changing Phase 1 request behavior or provider credential reads.
Gmail/Calendar/Drive authorization has been completed for the current Wanderra user,
and live end-to-end verification has succeeded for email, calendar events, and the
full Drive file lifecycle.

## Implemented capabilities

### Atlas Core H1-01

- Primary placement cell metadata.
- Mandatory business or personal organization records.
- Organization ownership records with deferred last-owner enforcement.
- Workspace records with immutable organization ownership during Phase 2.
- Forced workspace RLS on workspaces, audit events, and outbox events.
- Deterministic default personal organization/workspace backfill for existing Phase 1
  users.
- Immutable workspace-creation audit records and transactional outbox records.
- Fully reversible additive migration; Phase 1 tables and runtime routes are unchanged.

### Atlas Core H1-02

- Canonical global `User` model owned by the Identity bounded context.
- Lifecycle status, verification provenance, timestamps, and optimistic version.
- External identity links unique by issuer and subject.
- Duplicate verified email addresses remain distinct identities and never merge
  automatically.
- Existing Phase 1 user UUIDs and Gmail, Calendar, Drive, project, and conversation
  foreign keys are preserved.
- Atomic identity-migration audit and outbox evidence.
- Safe downgrade when no external links or duplicate emails exist; otherwise the
  migration requires an explicit reviewed forward fix.
- No session, invitation, recovery, MFA, membership, permission, or login behavior.

### Atlas Core H1-03

- Opaque server-side sessions persisted only as SHA-256 token hashes.
- Device, authentication-strength, recent-MFA, expiry, last-seen, and revocation
  state.
- Hashed, scoped, expiring, single-use invitation and recovery tokens.
- Row-lock concurrency protection against token replay.
- Atomic account recovery that revokes sessions and remaining recovery material.
- Reversible external-identity linking review with recent strong-authentication
  evidence.
- Durable security notifications plus transactional audit and outbox records.
- Secure host-only cookie policy and constant-time double-submit CSRF validation.
- Additive forced-RLS schema with guarded downgrade and no Phase 1 runtime wiring.

### Atlas Core H1-04

- Canonical membership records linking a user, organization, and workspace through
  composite tenant keys.
- Deterministic, versioned organization and workspace role classifications without
  capability mappings or policy evaluation.
- Invited, active, suspended, and revoked membership lifecycle.
- Single-use H1-03 invitation-token acceptance linked to the resulting membership.
- Immediate role and lifecycle version changes with transactional audit/outbox events.
- Deferred database invariants preserving an active workspace owner and personal
  organization consistency.
- Forced workspace RLS and repository methods that retain explicit workspace scope.
- Guarded rollback that refuses to discard post-migration membership state.
- No API, authorization engine, provider, agent, search, or memory changes.

### Atlas Core H1-05

- The H1-04 fixed system-role table is reused as the canonical Role model.
- H1-04 workspace memberships remain the canonical role assignments.
- Versioned canonical permission definitions and explicit fixed-role allow/deny rules.
- Uncached workspace-scoped permission lookup with explicit-deny precedence.
- Deny-first checks for workspace mismatch and invalid actor, session, or membership.
- Stable versioned authorization decisions and reason codes.
- Redacted transactional audit and outbox records for allow and deny decisions.
- Forced-RLS membership joins that cannot expose cross-workspace assignments.
- Guarded rollback that refuses to remove mutated catalogs or recorded decisions.
- No custom roles, inheritance, ABAC, APIs, provider access, agents, workflows,
  notifications, search, memory, or H1-06 context plumbing.

### Atlas Core H1-06

- Immutable, versioned request, actor, tenant, delegation, and correlation context.
- Request-scoped context binding with nested-scope isolation and guaranteed reset.
- Placement validation against canonical Organization, Workspace, and Cell records.
- Transaction-local PostgreSQL workspace, actor, session, membership, authorization
  decision, request, and correlation settings.
- Context-required repository base contract that rejects missing, mismatched, and
  cross-workspace execution.
- Safe audit/outbox trace references without session or membership identifier leakage.
- Forced-RLS validation under non-owner, non-bypass runtime roles.
- Pool reuse and deterministic replay tests proving context never leaks between
  transactions.
- Schema-free delivery with H1-05 downgrade/upgrade rehearsal; production remains at
  migration `0010_h1_authorization`.
- No Phase 1 route wiring, authorization changes, policy changes, providers, agents,
  jobs, workflows, notifications, search, memory, or H1-07 functionality.

### Atlas Core H1-07

- Versioned AES-256-GCM per-record envelope encryption with independently wrapped
  data-encryption keys.
- Tenant, connection, record-type, record-ID, and format-version authenticated data.
- Narrow asynchronous managed-KMS port and Google Cloud KMS production adapter.
- Immutable managed-key resource/version references with fail-closed provider errors.
- Context-bound envelope repository and forced workspace RLS.
- Idempotent KEK rewrap and DEK replacement with durable rotation checkpoints.
- Wrong-version, corrupted-ciphertext, provider-outage, and emergency-disable denial.
- Failure quarantine and redacted transactional audit/outbox evidence.
- Additive Gmail, Calendar, and Drive credential shadow columns; legacy ciphertext
  remains untouched and continues serving all Phase 1 runtime reads.
- Shadow equivalence verification, legacy checksums, explicit cutover state, and
  reauthorization fallback metadata.
- Guarded rollback that preserves legacy provider access and refuses to discard
  envelope migration state.
- No connection unification, provider runtime changes, agents, workflows, scheduler,
  jobs, notifications, search, memory, or H1-08 functionality.

### Atlas and memory

- Atlas chat endpoint backed by the configured OpenAI model.
- User, project, conversation, and conversation-message persistence.
- Embedding generation and cosine-similarity memory search.
- External-source identity fields for deduplicating imported messages.

### Gmail

- PKCE OAuth with encrypted refresh-token persistence.
- Incremental Google authorization compatible with Calendar and Drive grants.
- List recent messages, list unread messages, and Gmail-query search.
- Create drafts and send email.
- MIME generation and plain-text message parsing.
- Imported and sent messages are written to Atlas memory once per Gmail message ID.
- Live verification completed against `wanderra.world@gmail.com`.

### Google Calendar

- PKCE OAuth using the existing Google client and registered callback.
- List upcoming events.
- Create, update, and delete events.
- Timed and all-day event request support, including explicit time zones.
- Live create/update/delete lifecycle verified on the primary calendar.

### Google Drive

- Incremental PKCE OAuth that preserves the existing Gmail and Calendar scope grants.
- List and text-search files.
- Read file metadata.
- Download binary files and export Google Docs as plain text.
- Multipart upload.
- Update file metadata and replace file content.
- Delete files.
- Extract readable text from Google Docs, PDF, and DOCX.
- Synchronize observed file metadata into PostgreSQL on list, search, metadata read,
  download, upload, and update; remove the metadata row on deletion.
- Live reversible end-to-end verification completed for TXT, PDF, and DOCX, including
  cleanup in Drive and PostgreSQL.

## Architecture

```text
Client
  |
  | HTTP + X-User-ID
  v
FastAPI /api/v1
  |-- Atlas chat
  |-- Gmail service -------- Google Gmail API
  |-- Calendar service ----- Google Calendar API
  |-- Drive service -------- Google Drive API
  |
  |-- shared Google OAuth callback and scope validation
  |-- Fernet-encrypted provider credentials
  v
PostgreSQL
  |-- Atlas users/projects/conversations/memory
  |-- OAuth state and encrypted credentials per integration
  |-- synchronized Drive metadata
  `-- H1 organization/workspace placement, audit, and outbox foundation
```

The three Google integrations reuse one OAuth client configuration and the callback
registered at `/api/v1/gmail/oauth/callback`. A database-backed state value dispatches
the callback to Gmail, Calendar, or Drive. PKCE verifiers are persisted for the short
authorization window. Returned incremental scope sets are accepted only when they
contain the required integration scope and are a subset of the explicitly allowed
Gmail, Calendar, and Drive scopes.

Credentials are encrypted at rest with Fernet using
`GMAIL_CREDENTIALS_ENCRYPTION_KEY`. Google client secrets are mounted read-only into
the API container from `secrets/google`.

The Docker Compose stack contains:

- `api`: FastAPI/Uvicorn service on port 8000; applies Alembic migrations at startup.
- `db`: PostgreSQL 16 with a persistent named volume.

## Database schema

| Table | Purpose |
|---|---|
| `users` | Wanderra user identity and profile fields |
| `projects` | User-owned project records |
| `conversations` | User/project conversation containers |
| `conversation_messages` | Messages, embeddings, and optional external-source identity |
| `gmail_credentials` | Encrypted per-user Gmail credential |
| `gmail_oauth_states` | Expiring Gmail OAuth state and PKCE verifier |
| `calendar_credentials` | Encrypted per-user Calendar credential |
| `calendar_oauth_states` | Expiring Calendar OAuth state and PKCE verifier |
| `drive_credentials` | Encrypted per-user Drive credential |
| `drive_oauth_states` | Expiring Drive OAuth state and PKCE verifier |
| `drive_file_metadata` | Per-user cached Drive metadata keyed by Google file ID |
| `cells` | Workspace placement targets; H1 currently seeds one primary cell |
| `organizations` | Mandatory business or personal workspace owner |
| `organization_memberships` | Administrative owners and administrators; no implicit workspace access |
| `workspaces` | Primary tenant boundary with organization and cell placement |
| `audit_events` | Immutable workspace-scoped accountability records |
| `outbox_events` | Workspace-scoped transactional domain-event records |
| `external_identity_links` | Canonical login identities keyed by issuer and subject |

`drive_file_metadata` stores the file name, MIME type, size, modification time, view
link, MD5 checksum, parent IDs, the normalized provider payload, and synchronization
time. Deleting a file through Atlas also deletes its metadata row.

## API endpoints

All versioned endpoints use the `/api/v1` prefix. Integration routes require an
`X-User-ID` UUID header unless noted otherwise.

### Platform

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service liveness and environment |
| `POST` | `/api/v1/atlas/chat` | Send a message to Atlas |

### Gmail

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/gmail/oauth/authorize` | Start Gmail authorization |
| `GET` | `/api/v1/gmail/oauth/callback` | Shared Google OAuth callback |
| `GET` | `/api/v1/gmail/messages` | List recent messages |
| `GET` | `/api/v1/gmail/unread` | List unread messages |
| `GET` | `/api/v1/gmail/search` | Search using a Gmail query |
| `POST` | `/api/v1/gmail/draft` | Create a draft |
| `POST` | `/api/v1/gmail/send` | Send an email |

### Calendar

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/calendar/oauth/authorize` | Start Calendar authorization |
| `GET` | `/api/v1/calendar/events` | List ordered events |
| `POST` | `/api/v1/calendar/events` | Create an event |
| `PATCH` | `/api/v1/calendar/events/{event_id}` | Update an event |
| `DELETE` | `/api/v1/calendar/events/{event_id}` | Delete an event |

### Drive

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/drive/oauth/authorize` | Start Drive authorization |
| `GET` | `/api/v1/drive/files` | List files with pagination |
| `GET` | `/api/v1/drive/search` | Search names and indexed text |
| `GET` | `/api/v1/drive/files/{file_id}/metadata` | Read file metadata |
| `GET` | `/api/v1/drive/files/{file_id}/content` | Download/export content |
| `GET` | `/api/v1/drive/files/{file_id}/text` | Extract Google Docs/PDF/DOCX text |
| `POST` | `/api/v1/drive/files` | Upload a file |
| `PATCH` | `/api/v1/drive/files/{file_id}` | Update metadata |
| `PUT` | `/api/v1/drive/files/{file_id}/content` | Replace binary content |
| `DELETE` | `/api/v1/drive/files/{file_id}` | Delete a file |

Interactive OpenAPI documentation is available at `/docs`.

## Test coverage

The current automated suite contains 300 passing tests, with four
environment-dependent tests skipped:

- Health and Atlas chat API behavior.
- Gmail MIME construction and message parsing.
- Calendar request serialization, time validation, update validation, and response
  projection.
- Incremental Google OAuth acceptance for Gmail, Calendar, and Drive, plus rejection
  of missing or unexpected scopes.
- Drive search escaping and metadata normalization.
- Drive MIME dispatch regression coverage.
- PDF and DOCX extraction helpers.
- H0 architecture fitness, threat, isolation, authorization, encryption, custody,
  provider-conflict, lineage, AI security, entity integrity, and replay evidence.
- H1-01 model registration, composite tenant keys, PostgreSQL migration and rollback,
  deterministic ownership backfill, forced RLS, last-owner enforcement, transfer
  prohibition, and audit immutability.
- H1-02 canonical identity compatibility, duplicate-email safety, issuer/subject
  uniqueness, migration idempotency, atomic rollback, and forward-fix safeguards.
- H1-03 secret hashing, secure cookie and CSRF contracts, session rotation and
  revocation, invitation/recovery denial and replay rules, concurrent single use,
  atomic recovery, identity-link review, forced RLS, and guarded rollback.
- H1-04 membership modeling, fixed-role determinism, invitation acceptance,
  lifecycle transitions, repository scoping, composite-key attacks, forced RLS,
  migration backfill, rollback refusal, personal-workspace consistency, and
  concurrent last-owner preservation.
- H1-05 canonical roles and permissions, explicit allow/deny rules, deterministic
  decisions, unknown-permission denial, workspace mismatch denial, immediate
  revocation, forced-RLS permission joins, redacted audit/outbox evidence, migration
  rehearsal, and guarded rollback.
- H1-06 immutable execution contracts, request-scope reset, placement validation,
  transaction-local propagation, context-bound repositories, forced-RLS runtime
  roles, pool reset, deterministic replay, and schema-free rollback rehearsal.
- H1-07 managed-KMS contracts, authenticated encryption, key versioning, KEK and DEK
  rotation replay, legacy shadow verification, forced RLS, failure quarantine,
  emergency disable, additive migration, audit/outbox evidence, and guarded rollback.

Live integration verification has additionally covered:

- Gmail profile lookup, read/search operations, and email sending.
- Calendar listing and create/update/delete lifecycle.
- Drive list, search, upload, metadata read, binary download, PDF read, DOCX read,
  metadata/content update, deletion, and PostgreSQL synchronization before and after
  cleanup.

The test run currently emits one non-blocking Starlette/httpx deprecation warning.

## Known limitations

- `X-User-ID` remains trusted directly by Phase 1 routes; the H1-03 session lifecycle
  is intentionally not wired into production request authentication yet.
- H1-01 through H1-05 schema paths are intentionally unused by Phase 1 requests.
  Request context, memberships, authorization, commands, repositories, and provider
  migration remain later H1/H2 slices.
- The shared Google callback remains under the Gmail URL for compatibility with the
  currently registered OAuth client. A neutral callback path would be clearer.
- The Drive integration uses the broad `drive` scope. Production deployments should
  evaluate whether narrower scopes can satisfy the product requirements.
- OAuth credentials use an environment-provided symmetric key without managed key
  rotation or a cloud KMS.
- OAuth state rows expire logically but are not removed by a scheduled cleanup job.
- Gmail read operations store message content in memory by design; there is no
  per-request opt-out or retention policy.
- Calendar currently operates on a supplied calendar ID (default `primary`) but does
  not expose a calendar-list endpoint.
- Drive metadata is synchronized opportunistically, not through Drive change
  notifications. External changes remain stale until the file is observed again.
- File upload and download buffering occurs in memory. There are no application-level
  size limits, resumable upload endpoints, streaming responses, or malware scanning.
- Google Docs are exported as plain text. PDF extraction has no OCR, and DOCX
  extraction focuses on paragraph text rather than full layout, tables, comments, or
  embedded media.
- Search covers Drive `name` and `fullText` only and does not expose the complete Drive
  query language.
- Provider API calls have no application-level retry/backoff, rate-limit strategy,
  audit log, metrics, or tracing.
- Tests are strong at the unit and live-smoke level but do not yet mock complete Google
  API failure modes or run automatically in CI.

## Recommended next steps

1. Add real authentication and derive the Wanderra user from a verified session
   instead of `X-User-ID`.
2. Introduce a neutral `/api/v1/google/oauth/callback`, register it in Google Cloud,
   and migrate all three integrations to a shared OAuth coordinator.
3. Add CI for linting, migrations, unit tests, and provider-contract tests; resolve the
   Starlette/httpx deprecation warning.
4. Add structured logs, audit records for external mutations, request IDs, metrics,
   tracing, retry/backoff, and quota-aware error handling.
5. Add streaming downloads, resumable uploads, explicit file-size limits, MIME/content
   validation, and malware scanning.
6. Add Drive change notifications or periodic reconciliation so PostgreSQL metadata
   reflects external edits and deletions.
7. Add a calendar-list endpoint, recurring-event controls, attendee notification
   options, and conflict/time-zone tests.
8. Add retention, redaction, and user-control policies for Gmail content stored in
   Atlas memory.
9. Move credential encryption to a managed KMS with key versioning and rotation, and
   add scheduled cleanup for expired OAuth states.
10. Expand document ingestion with OCR, table-aware DOCX parsing, richer Google Docs
    structure, chunking, and memory indexing for Atlas retrieval.
