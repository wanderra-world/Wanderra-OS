"""Interactive, first-run verification and connection wizard for Wanderra OS."""

import argparse
import asyncio
import importlib.util
import queue
import secrets
import sys
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet

from openai import AsyncOpenAI
from sqlalchemy import select, text

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal, engine
from app.integrations.gmail.service import GmailConfigurationError, GmailNotConnectedError, GmailService
from app.memory.embeddings import OpenAIEmbeddingProvider
from app.memory.repositories import SQLAlchemyMemoryRepository
from app.memory.search import CosineSimilaritySearchBackend
from app.memory.service import MemoryService
from app.models.memory import User


def _status(name: str, ok: bool, detail: str) -> tuple[str, bool, str]:
    return name, ok, detail


def bootstrap_environment() -> None:
    """Create a safe local `.env` without ever writing third-party API secrets."""
    from pathlib import Path

    env_path = Path(".env")
    if env_path.exists():
        print(".env already exists; leaving it unchanged.")
        return
    database_password = secrets.token_urlsafe(32)
    env_path.write_text(
        "\n".join(
            [
                "APP_NAME=Wanderra OS",
                "APP_ENV=development",
                "DEBUG=true",
                "API_V1_PREFIX=/api/v1",
                "LOG_LEVEL=INFO",
                "POSTGRES_DB=wanderra",
                "POSTGRES_USER=wanderra",
                f"POSTGRES_PASSWORD={database_password}",
                f"DATABASE_URL=postgresql+asyncpg://wanderra:{database_password}@localhost:5432/wanderra",
                "OPENAI_API_KEY=",
                "OPENAI_MODEL=gpt-5",
                "OPENAI_EMBEDDING_MODEL=text-embedding-3-small",
                "GOOGLE_OAUTH_CLIENT_SECRET_FILE=secrets/google/client_secret.json",
                "GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/gmail/oauth/callback",
                f"GMAIL_CREDENTIALS_ENCRYPTION_KEY={Fernet.generate_key().decode()}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print("Created .env with generated PostgreSQL and Gmail-encryption secrets.")


def _wait_for_callback(redirect_uri: str, timeout: int = 300) -> tuple[str, str]:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("GOOGLE_OAUTH_REDIRECT_URI must use a local http://localhost callback for automatic setup.")
    received: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1)

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path != parsed.path:
                self.send_error(404)
                return
            values = parse_qs(urlparse(self.path).query)
            if "code" in values and "state" in values:
                received.put((values["state"][0], values["code"][0]))
                body = b"<h1>Wanderra Gmail connected</h1><p>You can return to the setup wizard.</p>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(400, "Google did not return an authorization code.")

        def log_message(self, *_: object) -> None:
            return

    server = HTTPServer((parsed.hostname, parsed.port or 80), CallbackHandler)
    try:
        return _serve_once(server, received, timeout)
    finally:
        server.server_close()


def _serve_once(server: HTTPServer, received: queue.Queue[tuple[str, str]], timeout: int) -> tuple[str, str]:
    server.timeout = 1
    deadline = datetime.now(UTC).timestamp() + timeout
    while datetime.now(UTC).timestamp() < deadline:
        server.handle_request()
        try:
            return received.get_nowait()
        except queue.Empty:
            pass
    raise TimeoutError("Timed out waiting for Google OAuth consent.")


async def run(email: str | None, skip_gmail: bool) -> int:
    statuses: list[tuple[str, bool, str]] = []
    required = ["fastapi", "sqlalchemy", "alembic", "openai", "googleapiclient", "google_auth_oauthlib", "cryptography"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    dependencies_ready = sys.version_info >= (3, 12) and not missing
    dependency_detail = "ready" if dependencies_ready else (
        f"requires Python 3.12; running {sys.version.split()[0]}" if sys.version_info < (3, 12) else f"missing: {', '.join(missing)}"
    )
    statuses.append(_status("Python dependencies", dependencies_ready, dependency_detail))
    settings = get_settings()

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        statuses.append(_status("PostgreSQL", True, "connected"))
    except Exception as error:
        statuses.append(_status("PostgreSQL", False, str(error)))

    if settings.openai_api_key is None:
        statuses.append(_status("OpenAI", False, "OPENAI_API_KEY is not configured"))
    else:
        try:
            async for _ in AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value()).models.list():
                break
            statuses.append(_status("OpenAI", True, "API key accepted"))
        except Exception as error:
            statuses.append(_status("OpenAI", False, str(error)))

    if not skip_gmail:
        if email is None:
            email = f"gmail-setup-{secrets.token_hex(12)}@local.wanderra"
        try:
            async with AsyncSessionLocal() as session:
                user = await session.scalar(select(User).where(User.email == email))
                if user is None:
                    user = User(email=email)
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
                memory = MemoryService(SQLAlchemyMemoryRepository(session), OpenAIEmbeddingProvider(), CosineSimilaritySearchBackend())
                gmail = GmailService(session, memory)
                try:
                    address = await gmail.test_connection(user.id)
                    if user.email.endswith("@local.wanderra"):
                        user.email = address
                        await session.commit()
                    statuses.append(_status("Gmail", True, f"connected as {address}"))
                except GmailNotConnectedError:
                    authorization_url = await gmail.authorization_url(user.id)
                    print("\nOpening Google OAuth consent in your browser…")
                    webbrowser.open(authorization_url, new=1)
                    state, code = await asyncio.to_thread(_wait_for_callback, settings.google_oauth_redirect_uri)
                    await gmail.complete_oauth(state, code)
                    address = await gmail.test_connection(user.id)
                    if user.email.endswith("@local.wanderra"):
                        user.email = address
                        await session.commit()
                    statuses.append(_status("Gmail", True, f"connected as {address}"))
        except Exception as error:
            statuses.append(_status("Gmail", False, str(error)))
    else:
        statuses.append(_status("Gmail", False, "skipped by request"))

    print("\nWanderra OS setup status")
    print("-" * 44)
    for name, ok, detail in statuses:
        print(f"{'CONNECTED' if ok else 'NEEDS ATTENTION':<16} {name}: {detail}")
    await engine.dispose()
    return 0 if all(ok for _, ok, _ in statuses) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Wanderra OS first-run setup.")
    parser.add_argument("--email", help="Email for the Wanderra user linked to Gmail.")
    parser.add_argument("--skip-gmail", action="store_true", help="Skip browser-based Gmail OAuth.")
    parser.add_argument("--bootstrap", action="store_true", help="Create .env with generated local secrets if absent.")
    args = parser.parse_args()
    if args.bootstrap:
        bootstrap_environment()
    raise SystemExit(asyncio.run(run(args.email, args.skip_gmail)))
