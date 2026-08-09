"""One-shot localhost runner for the ADR-036 bootstrap ceremony."""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import Settings, get_settings
from app.database.session import AsyncSessionLocal, close_database_connection
from app.execution_context import (
    ActorContext,
    ExecutionContext,
    ExecutionContextService,
    RequestContext,
    TenantContext,
)
from app.identity.bootstrap import (
    FIXED_BOOTSTRAP_USER_ID,
    FIXED_BOOTSTRAP_WORKSPACE_ID,
    BootstrapApproval,
    BootstrapIdentity,
    BootstrapIdentityError,
    BootstrapIdentityLinkService,
)
from app.integrations.google_identity.oidc import (
    GoogleOIDCConfiguration,
    GoogleOIDCError,
    GoogleOIDCProtocol,
)
from app.memberships.models import WorkspaceMembership
from app.tenancy.models import Workspace

CALLBACK_PATH = "/api/v1/operator/auth/google/callback"
START_PATH = "/start"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8000
CEREMONY_TIMEOUT_SECONDS = 600


def _configuration(settings: Settings) -> GoogleOIDCConfiguration:
    client_id = settings.google_oauth_client_id
    client_secret = (
        settings.google_oauth_client_secret.get_secret_value()
        if settings.google_oauth_client_secret is not None
        else None
    )
    client_file = Path(settings.google_oauth_client_secret_file)
    if client_file.is_file():
        document = json.loads(client_file.read_text())
        values = document.get("web")
        if not isinstance(values, dict):
            raise BootstrapIdentityError("bootstrap requires a Google Web OAuth client")
        client_id = str(values.get("client_id", ""))
        client_secret = str(values.get("client_secret", ""))
    if client_id is None or client_secret is None:
        raise BootstrapIdentityError("Google operator authentication is not configured")
    if settings.google_operator_oidc_redirect_uri != (
        f"http://localhost:{LISTEN_PORT}{CALLBACK_PATH}"
    ):
        raise BootstrapIdentityError("operator redirect does not match bootstrap listener")
    return GoogleOIDCConfiguration(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=settings.google_operator_oidc_redirect_uri,
    )


async def _context(approval_reference: str) -> ExecutionContext:
    async with AsyncSessionLocal() as session:
        workspace = await session.get(Workspace, FIXED_BOOTSTRAP_WORKSPACE_ID)
        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == FIXED_BOOTSTRAP_WORKSPACE_ID,
                WorkspaceMembership.user_id == FIXED_BOOTSTRAP_USER_ID,
            )
        )
    if workspace is None or membership is None:
        raise BootstrapIdentityError("fixed bootstrap target is unavailable")
    return ExecutionContext(
        request=RequestContext(
            request_id=approval_reference,
            correlation_id=approval_reference,
        ),
        actor=ActorContext(
            actor_id=FIXED_BOOTSTRAP_USER_ID,
            session_id=uuid.UUID(int=0),
            membership_id=membership.id,
            authorization_decision_id=uuid.UUID(int=0),
        ),
        tenant=TenantContext(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            cell_id=workspace.cell_id,
        ),
    )


async def _require_ready(context: ExecutionContext) -> None:
    async with AsyncSessionLocal() as session:
        async with ExecutionContextService().transaction(session, context):
            await BootstrapIdentityLinkService(session).require_ready()


async def _commit(
    context: ExecutionContext,
    identity: BootstrapIdentity,
    approval: BootstrapApproval,
) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as session:
        async with ExecutionContextService().transaction(session, context):
            result = await BootstrapIdentityLinkService(session).commit(
                identity=identity,
                approval=approval,
            )
    return result.external_identity_link_id, result.audit_event_id


class _CeremonyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def _handler(
    *,
    protocol: GoogleOIDCProtocol,
    authorization_url: str,
    transaction_cookie: str,
    audience: str,
    completed: Queue[BootstrapIdentity | Exception],
) -> type[BaseHTTPRequestHandler]:
    callback_lock = threading.Lock()
    callback_used = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _reply(self, status: HTTPStatus, message: str) -> None:
            body = message.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            nonlocal callback_used
            request = urlsplit(self.path)
            if request.path == START_PATH:
                self.send_response(HTTPStatus.TEMPORARY_REDIRECT)
                self.send_header("Location", authorization_url)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if request.path != CALLBACK_PATH:
                self._reply(HTTPStatus.NOT_FOUND, "Not found.")
                return
            with callback_lock:
                if callback_used:
                    self._reply(HTTPStatus.CONFLICT, "Bootstrap callback already consumed.")
                    return
                callback_used = True
            query = parse_qs(request.query, strict_parsing=True)
            code = query.get("code", [])
            state = query.get("state", [])
            if len(code) != 1 or len(state) != 1:
                error = BootstrapIdentityError("bootstrap callback is incomplete")
                completed.put(error)
                self._reply(HTTPStatus.BAD_REQUEST, "Bootstrap verification failed.")
                return
            try:
                result = asyncio.run(
                    protocol.complete(
                        code=code[0],
                        state=state[0],
                        transaction_cookie=transaction_cookie,
                        now=datetime.now(UTC),
                    )
                )
                identity = BootstrapIdentity(
                    issuer=result.claims.issuer,
                    subject=result.claims.subject,
                    audience=audience,
                    verified_at=datetime.now(UTC),
                )
            except (GoogleOIDCError, BootstrapIdentityError, ValueError) as error:
                completed.put(error)
                self._reply(HTTPStatus.FORBIDDEN, "Bootstrap verification failed.")
                return
            completed.put(identity)
            self._reply(
                HTTPStatus.OK,
                "Google identity verified. Return to Codex for final approval; "
                "no Atlas identity link has been created.",
            )

    return Handler


def _verify_google_identity(configuration: GoogleOIDCConfiguration) -> BootstrapIdentity:
    protocol = GoogleOIDCProtocol(configuration)
    started = protocol.start(workspace_id=FIXED_BOOTSTRAP_WORKSPACE_ID)
    completed: Queue[BootstrapIdentity | Exception] = Queue(maxsize=1)
    server = _CeremonyServer(
        (LISTEN_HOST, LISTEN_PORT),
        _handler(
            protocol=protocol,
            authorization_url=started.authorization_url,
            transaction_cookie=started.transaction_cookie,
            audience=configuration.client_id,
            completed=completed,
        ),
    )
    server.timeout = 1
    deadline = time.monotonic() + CEREMONY_TIMEOUT_SECONDS
    print(f"Open http://localhost:{LISTEN_PORT}{START_PATH} in the browser.", flush=True)
    try:
        while completed.empty() and time.monotonic() < deadline:
            server.handle_request()
        if completed.empty():
            raise BootstrapIdentityError("bootstrap ceremony expired")
        result = completed.get_nowait()
        if isinstance(result, Exception):
            raise BootstrapIdentityError("Google identity verification failed") from result
        return result
    finally:
        server.server_close()


async def _run(approval_reference: str) -> int:
    context = await _context(approval_reference)
    await _require_ready(context)
    configuration = _configuration(get_settings())
    identity = _verify_google_identity(configuration)
    print(f"VERIFIED_ISSUER={identity.issuer}", flush=True)
    print(f"VERIFIED_SUBJECT={identity.subject}", flush=True)
    print(f"SUBJECT_FINGERPRINT={identity.subject_fingerprint}", flush=True)
    confirmation = (
        "APPROVE ADR-036 LINK "
        f"issuer={identity.issuer} subject={identity.subject} "
        f"user={FIXED_BOOTSTRAP_USER_ID} workspace={FIXED_BOOTSTRAP_WORKSPACE_ID}"
    )
    print("FINAL_APPROVAL_REQUIRED", flush=True)
    supplied = input()
    if supplied != confirmation:
        raise BootstrapIdentityError("final bootstrap approval did not match")
    approval = BootstrapApproval(
        reference=approval_reference,
        user_id=FIXED_BOOTSTRAP_USER_ID,
        workspace_id=FIXED_BOOTSTRAP_WORKSPACE_ID,
        issuer=identity.issuer,
        subject=identity.subject,
    )
    link_id, audit_id = await _commit(context, identity, approval)
    print(f"EXTERNAL_IDENTITY_LINK_ID={link_id}", flush=True)
    print(f"AUDIT_EVENT_ID={audit_id}", flush=True)
    print("BOOTSTRAP_DISABLED=yes", flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the one-time ADR-036 bootstrap")
    parser.add_argument("--approval-reference", required=True)
    arguments = parser.parse_args()
    async def execute() -> int:
        try:
            return await _run(arguments.approval_reference)
        finally:
            await close_database_connection()

    try:
        raise SystemExit(asyncio.run(execute()))
    except (BootstrapIdentityError, GoogleOIDCError, ValueError, OSError) as error:
        print(f"Bootstrap denied: {error}", flush=True)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
