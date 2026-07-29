# Atlas Long-Term Roadmap

**Owner:** Atlas Product and Engineering Leadership

## Roadmap rules

- Preserve the operational Phase 1 integrations throughout migration.
- Build foundations in dependency order; do not build advanced AI over weak tenancy.
- Every phase has exit criteria, migrations, security tests, and operational telemetry.
- Prefer vertical slices that exercise domain, API, events, jobs, audit, and search.
- Feature work does not bypass architectural invariants for speed.

## Phase 1: Google Workspace Foundation — complete

Delivered:

- Gmail, Google Calendar, and Google Drive.
- OAuth 2.0, incremental scopes, PKCE, encrypted credentials.
- PostgreSQL, FastAPI, Docker, migrations, tests, and live end-to-end validation.

Correction: embeddings are currently JSONB with Python cosine search. Production
pgvector remains Phase 2 work.

## Phase 2A: Tenancy and security foundation

### Deliver

- Organizations and workspaces.
- Verified authentication and session lifecycle.
- Workspace memberships and invitations.
- Roles, permissions, and policy evaluation.
- Immutable request/actor context.
- Workspace ownership on all existing tenant data.
- Workspace-scoped uniqueness and cross-tenant isolation tests.
- Audit event foundation and correlation IDs.

### Migrate

- Create a default organization and Wanderra workspace.
- Assign the current user as owner.
- Backfill projects, conversations, messages, credentials, OAuth state, and Drive
  metadata.
- Replace `X-User-ID` trust with verified identity; retain a controlled development
  mechanism only outside production.

### Exit criteria

- No tenant-owned row lacks `workspace_id`.
- Cross-workspace access is denied in application tests and PostgreSQL RLS tests.
- All material mutations emit an audit event.
- Phase 1 workflows remain operational.

## Phase 2B: Provider-neutral connections

### Deliver

- Unified connections, credential envelopes, OAuth transactions, capability grants,
  sync cursors, webhook subscriptions, and external references.
- Neutral email, calendar, and storage provider ports.
- Google adapters behind those ports.
- Provider-neutral API schemas and error taxonomy.
- Transactional outbox and idempotent event consumers.
- Durable job runner with retries, leases, dead letters, and cancellation.

### Migrate

- Convert Gmail, Calendar, and Drive credentials into workspace connections.
- Move callback dispatch from integration-table probing to OAuth transaction lookup.
- Preserve valid refresh credentials where possible.
- Dual-run selected reads and compare canonical responses before removing old paths.

### Exit criteria

- Business/application code imports no Google SDK types.
- A mock second provider passes shared contract tests.
- Sync jobs are replayable and idempotent.
- Provider errors are classified consistently.

## Phase 2C: Universal entity and core operations

### Deliver

- Entity registry and typed entity projections.
- Entity relationships and relationship type registry.
- Tags, attachments, ownership, resource grants, and AI/human notes.
- Contacts, companies, projects, and tasks as first typed modules.
- Provider external references linked to canonical entities.
- Optimistic concurrency and entity versioning.

### Exit criteria

- Generic features target any registered entity.
- Operational invariants remain in typed aggregates.
- External identity collisions are scoped by workspace and connection.
- At least one complete slice links contact → company → project → task → email/file.

## Phase 2D: Documents, timeline, knowledge, and memory

### Deliver

- Logical documents and immutable document versions.
- Extraction pipeline and versioned content chunks.
- User-facing timeline projection.
- Evidence-backed claims and contradiction handling.
- Governed memory items, sources, feedback, expiry, and supersession.
- Retention, deletion, and sensitivity policies.

### Exit criteria

- Operational truth, source, claim, memory, timeline, and audit are distinguishable in
  storage and API.
- Every extracted claim/memory can identify its source evidence.
- Deletion and retention behavior is tested across derived artifacts.

## Phase 2E: Search platform

### Deliver

- PostgreSQL full-text indexes.
- pgvector extension and versioned embeddings.
- Permission-aware search documents.
- Hybrid lexical/vector/structured ranking.
- Graph-neighborhood expansion.
- Indexing jobs, freshness metrics, and reindex tooling.

### Exit criteria

- Workspace and visibility filters execute before retrieval.
- Search does not load all embeddings into application memory.
- Model and chunking migrations can run side by side.
- Relevance, isolation, latency, and stale-index tests meet defined SLOs.

## Phase 2F: Core product surfaces

### Deliver

- Workspace switcher and administration.
- Entity views with relationships, timeline, notes, tags, attachments, and audit.
- Universal search.
- Connection health and sync status.
- Task/project/contact workflows.
- Notification and activity center.

### Exit criteria

- All initial workspaces can be created and independently configured.
- Workspace exports and deletion workflows exist.
- Operational support can diagnose sync and authorization problems without database
  access.

## Phase 3: Business modules

Build reusable domains before workspace-specific variants.

### Shared modules

- CRM and client management.
- Documents and records.
- Finance ingestion and invoice workflow.
- Assets and maintenance.
- Scheduling and field operations.
- Logistics and shipments.
- Commerce/catalog/orders where required.

### Workspace rollout

Roll out in controlled order based on business value and data sensitivity:

1. Wanderra as reference workspace.
2. Skandihus and Vilken Fin Städning.
3. Logistics.
4. Nordic Lusso and Andelle Mia.
5. Soft Power Women and Men's Club.
6. Personal with stricter privacy defaults.

Each rollout defines roles, connections, retention, entity types, workflows, dashboards,
and acceptance tests. Avoid company-named forks of core code.

## Phase 4A: AI assistance

### Deliver

- Permission-aware context builder.
- Evidence-linked answers and smart search.
- Structured recommendations and feedback.
- Daily briefings.
- Meeting/email/document summaries.
- Suggested tasks, relationships, and knowledge claims.
- Evaluation datasets and observability.

### Exit criteria

- Answers cite accessible sources.
- Hallucination, leakage, and retrieval evaluations run continuously.
- Recommendations are stored, explainable, dismissible, and measurable.

## Phase 4B: Governed agents and workflows

### Deliver

- Agent registry and specialized agents.
- Structured planner and versioned plans.
- Durable workflow execution.
- Tool risk metadata and budgets.
- Approval policies and action digests.
- Verification and compensation.
- Agent audit and outcome evaluation.

### Exit criteria

- Agents cannot bypass application authorization.
- High-risk operations require correct approval.
- Duplicate delivery cannot duplicate external effects.
- Every action is verified or explicitly marked uncertain.
- Emergency disable and per-workspace autonomy controls exist.

## Phase 5: Provider and ecosystem expansion

Prioritize by demand:

- Microsoft 365: Outlook, Calendar, OneDrive, Teams.
- Exchange and IMAP/SMTP.
- Slack and Discord.
- Dropbox.
- WhatsApp and Telegram.
- Stripe and finance providers.
- Shopify.
- HubSpot and other CRMs.

Every adapter must pass capability contracts, security review, sync/reconciliation tests,
quota tests, and workspace-isolation tests.

## Phase 6: Platform scale and ecosystem

- Public integration SDK and manifest format.
- Partner adapter certification.
- Organization-level policy and billing.
- Optional cross-workspace collaboration.
- Regional placement and dedicated tenant databases.
- Compliance programs appropriate to market.
- Advanced event infrastructure or service extraction based on measured load.

## First production milestone after H0

The canonical H0–H8 ordering and purpose are owned by
[ARCHITECTURE_HARDENING.md](ARCHITECTURE_HARDENING.md#revised-phase-2-implementation-sequence).
Engineering gates and pull-request rules are owned by
[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md#3-canonical-implementation-order).
The live H0 evidence status and authorized next validation slice are owned by
[H0_FOUNDATION_SPEC.md](H0_FOUNDATION_SPEC.md#17-h0-approval-and-exit-evidence).
