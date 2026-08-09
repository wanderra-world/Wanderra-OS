# Wanderra OS

**Owner:** Atlas Platform Engineering

Wanderra OS is a production-oriented foundation for an AI-native operating system. It provides a modular FastAPI service, PostgreSQL persistence, migrations, integration boundaries, AI memory abstractions, and a home for background automation.

## Architecture

```text
app/
  core/          Configuration, logging, and shared application concerns
  api/           Versioned HTTP endpoints and request dependencies
  database/      SQLAlchemy base, engine, and session lifecycle
  models/        ORM entities
  services/      Reusable application and business logic
  agents/        Autonomous-agent orchestration and tool contracts
  integrations/  Clients for external providers and APIs
  memory/        Embeddings, vector memory, knowledge ingestion, retrieval
  workers/       Background jobs, queues, schedulers, and synchronization
tests/           API and component-level tests
alembic/         Database migration environment and revisions
```

`services` is the application boundary shared by API endpoints, agents, and workers. Provider-specific code belongs in `integrations`, while `memory` owns the vector and retrieval layer. PostgreSQL is the system of record; the eventual vector-store provider remains intentionally configurable.

## Atlas Memory

The memory module persists users, projects, conversations, and individual conversation messages in PostgreSQL. Each stored message is embedded with OpenAI's embeddings API and saved alongside its text. `MemoryService.search_conversations()` embeds the query and ranks a user's prior messages by cosine similarity, with an optional project scope.

The public memory service depends only on three contracts: `MemoryRepository`, `EmbeddingProvider`, and `SemanticSearchBackend`. The default PostgreSQL implementation stores vectors as JSONB and computes similarity in the application, which is a durable foundation for moderate data volumes. A pgvector, Pinecone, Weaviate, or other vector database adapter can implement `SemanticSearchBackend` later without changing the service, its callers, or the API surface.

Run migrations after pulling the module:

```bash
alembic upgrade head
```

## Quick start with Docker

1. Copy the environment template: `cp .env.example .env`
2. Replace `POSTGRES_PASSWORD` with a secure local value.
3. Start the stack: `docker compose up --build`
4. Open `http://localhost:8000/docs` or check `http://localhost:8000/health`.

The API container runs `alembic upgrade head` on startup. Set `RUN_MIGRATIONS=false` if migrations are managed separately in a deployment environment.

## First-run setup wizard

After filling in `.env` and starting PostgreSQL, run the wizard to validate the stack, test OpenAI, and connect Gmail with a browser-based OAuth consent flow:

```bash
wanderra-setup --email you@example.com
```

The wizard verifies the required Python packages, PostgreSQL, OpenAI API key, and Gmail configuration. It automatically opens the Google consent page, receives the localhost OAuth callback, encrypts and stores the refresh credential, tests the connected Gmail account, and prints a final service-by-service report. Use `--skip-gmail` only when Gmail OAuth is intentionally deferred.

## Configure Atlas

Atlas uses the official OpenAI Python SDK and the Responses API. To enable it:

1. Create an API key in the [OpenAI API key dashboard](https://platform.openai.com/api-keys).
2. Copy `.env.example` to `.env` if you have not already done so.
3. Set `OPENAI_API_KEY` in `.env` to the new key. Do not commit this file.
4. Optionally set `OPENAI_MODEL`; it defaults to `gpt-5`.
5. Start the API, then send a request:

```bash
curl -X POST http://localhost:8000/api/v1/atlas/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hello, Atlas"}'
```

The response has the shape `{"reply":"..."}`. If `OPENAI_API_KEY` is not set, the endpoint returns `503 Service Unavailable` without attempting a remote call.

## Gmail integration

1. In Google Cloud, create a project, enable the Gmail API, configure an OAuth consent screen, and create a **Web application** OAuth client. Add the value of `GOOGLE_OAUTH_REDIRECT_URI` as an authorized redirect URI.
2. Place the downloaded OAuth client JSON at `secrets/google/client_secret.json`. This directory is ignored by Git. The integration reads it directly; do not copy its client secret into source control.
3. Run `wanderra-setup --bootstrap --email you@example.com` to create `.env` with generated database and encryption secrets, then add only `OPENAI_API_KEY` to that file.
4. Apply migrations: `alembic upgrade head`.
5. Create a Wanderra user, then initiate OAuth with `GET /api/v1/gmail/oauth/authorize` and an `X-User-ID` UUID header. Open the returned URL and complete consent. Google redirects to the callback, which saves the encrypted refresh credential.
6. Use the same `X-User-ID` header with `/api/v1/gmail/messages`, `/unread`, `/search?query=...`, `/draft`, and `/send`.

Messages returned by read endpoints and messages sent through Wanderra are stored in Atlas Memory exactly once per Gmail message ID. Drafts remain outside long-term memory until sent.

## Google Calendar and Drive integrations

Calendar and Drive reuse the Gmail OAuth client, encrypted credential key, and registered
callback. Enable the Google Calendar API and Google Drive API in the same Google Cloud
project, then authorize each integration incrementally:

- `GET /api/v1/calendar/oauth/authorize`
- `GET /api/v1/drive/oauth/authorize`

Pass the Wanderra user UUID in `X-User-ID` and open the returned authorization URL.
Google may return the union of previously granted Gmail, Calendar, and Drive scopes; the
shared callback validates and accepts that allowed scope set.

Drive endpoints support listing (`GET /drive/files`), searching (`GET /drive/search`),
metadata, binary downloads, multipart uploads, metadata/content updates, deletion, and
text extraction (`GET /drive/files/{file_id}/text`) for Google Docs, PDF, and DOCX.
Metadata observed through Drive operations is synchronized to PostgreSQL.

## Local development

Use Python 3.12 or later.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload
```

For local execution outside Docker, set `DATABASE_URL` to point to your PostgreSQL instance (for example, use `localhost` instead of `db`).

## Database migrations

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic downgrade -1
```

Keep ORM model imports available through `app.models` so Alembic can discover all table metadata.

## Tests and linting

```bash
pytest
ruff check .
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Human-readable application name |
| `APP_ENV` | Runtime environment, such as `development` or `production` |
| `DEBUG` | Enables development-only debugging behavior |
| `API_V1_PREFIX` | Prefix for versioned API routes |
| `LOG_LEVEL` | Application log verbosity |
| `OPENAI_API_KEY` | Secret API key used by Atlas; required for `/api/v1/atlas/chat` |
| `OPENAI_MODEL` | OpenAI model used by Atlas; defaults to `gpt-5` |
| `OPENAI_EMBEDDING_MODEL` | Model used to create semantic memory embeddings; defaults to `text-embedding-3-small` |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth web client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth web client secret |
| `GOOGLE_OAUTH_CLIENT_SECRET_FILE` | Google OAuth web-client JSON secret file; takes precedence over separate client variables |
| `GOOGLE_OAUTH_REDIRECT_URI` | Registered OAuth callback URL |
| `GOOGLE_OAUTH_WORKSPACE_REDIRECT_URI` | Registered workspace Gmail authorization callback URL |
| `GOOGLE_OPERATOR_OIDC_REDIRECT_URI` | Registered Google Identity operator-login callback URL |
| `GMAIL_CREDENTIALS_ENCRYPTION_KEY` | Fernet key used to encrypt Gmail OAuth credentials at rest |
| `ATLAS_KMS_PROVIDER` | Managed envelope-encryption key provider |
| `ATLAS_KMS_KEY_RESOURCE` | Managed KMS key resource; never a key value |
| `ATLAS_KMS_KEY_VERSION` | Approved managed KMS key version |
| `DATABASE_URL` | Async SQLAlchemy PostgreSQL connection URL |
| `POSTGRES_DB` | Database name used by Docker Compose |
| `POSTGRES_USER` | Database user used by Docker Compose |
| `POSTGRES_PASSWORD` | Database password; never commit the real value |
