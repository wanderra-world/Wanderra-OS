"""ADR-035 Google Identity login and canonical Atlas session lifecycle API."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.database.session import get_db_session
from app.identity.lifecycle import IdentityLifecycleService, InvalidSessionError, validate_csrf
from app.identity.operator_auth import (
    OperatorAuthenticationError,
    OperatorAuthenticationService,
)
from app.integrations.google_identity.oidc import (
    GoogleOIDCConfiguration,
    GoogleOIDCError,
    GoogleOIDCProtocol,
)
from app.memberships.repository import WorkspaceMembershipRepository

router = APIRouter()

OIDC_COOKIE = "__Host-atlas_oidc"
SESSION_COOKIE = "__Host-atlas_session"
CSRF_COOKIE = "__Host-atlas_csrf"
OIDC_COOKIE_MAX_AGE = 600
SESSION_COOKIE_MAX_AGE = 43_200


class OperatorSessionResponse(BaseModel):
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    session_id: uuid.UUID
    expires_at: datetime


def _configuration(settings: Settings) -> GoogleOIDCConfiguration:
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    client_file = Path(settings.google_oauth_client_secret_file)
    secret_value: str | None = None
    if client_file.is_file():
        try:
            document = json.loads(client_file.read_text())
            values = document.get("web") or document.get("installed")
            client_id = str(values["client_id"])
            secret_value = str(values["client_secret"])
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Google operator authentication configuration is invalid.",
            ) from error
    elif client_id is not None and client_secret is not None:
        secret_value = client_secret.get_secret_value()
    if client_id is None or secret_value is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google operator authentication is not configured.",
        )
    try:
        return GoogleOIDCConfiguration(
            client_id=client_id,
            client_secret=secret_value,
            redirect_uri=settings.google_operator_oidc_redirect_uri,
        )
    except ValueError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google operator authentication configuration is invalid.",
        ) from error


def get_google_oidc_protocol() -> GoogleOIDCProtocol:
    return GoogleOIDCProtocol(_configuration(get_settings()))


def _set_host_cookie(
    response: Response,
    *,
    key: str,
    value: str,
    max_age: int,
) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear_operator_cookies(response: Response) -> None:
    for key in (OIDC_COOKIE, SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(key, secure=True, httponly=True, samesite="lax", path="/")


def _oidc_cookie_deletion_header() -> str:
    response = Response()
    response.delete_cookie(
        OIDC_COOKIE,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response.headers["set-cookie"]


@router.get("/auth/google/start", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def start_google_operator_authentication(
    workspace_id: uuid.UUID,
    protocol: Annotated[GoogleOIDCProtocol, Depends(get_google_oidc_protocol)],
) -> RedirectResponse:
    started = protocol.start(workspace_id=workspace_id)
    response = RedirectResponse(
        started.authorization_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    _set_host_cookie(
        response,
        key=OIDC_COOKIE,
        value=started.transaction_cookie,
        max_age=OIDC_COOKIE_MAX_AGE,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/google/callback", response_model=OperatorSessionResponse)
async def complete_google_operator_authentication(
    response: Response,
    code: str,
    state_value: Annotated[str, Query(alias="state")],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    protocol: Annotated[GoogleOIDCProtocol, Depends(get_google_oidc_protocol)],
    transaction_cookie: Annotated[str | None, Cookie(alias=OIDC_COOKIE)] = None,
    user_agent: Annotated[str | None, Header(alias="User-Agent")] = None,
) -> OperatorSessionResponse:
    if transaction_cookie is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Operator login is invalid.")
    checked_at = datetime.now(UTC)
    try:
        completed = await protocol.complete(
            code=code,
            state=state_value,
            transaction_cookie=transaction_cookie,
            now=checked_at,
        )
        async with session.begin():
            await session.execute(
                text("SELECT set_config('atlas.workspace_id', :workspace_id, TRUE)"),
                {"workspace_id": str(completed.workspace_id)},
            )
            grant = await OperatorAuthenticationService.for_session(session).authenticate(
                claims=completed.claims,
                workspace_id=completed.workspace_id,
                device_id=(
                    "browser:"
                    + hashlib.sha256((user_agent or "unknown-browser").encode()).hexdigest()
                ),
                now=checked_at,
            )
    except (GoogleOIDCError, OperatorAuthenticationError, ValueError) as error:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Operator login was denied.",
            headers={
                "Cache-Control": "no-store",
                "Set-Cookie": _oidc_cookie_deletion_header(),
            },
        ) from error
    _set_host_cookie(
        response,
        key=SESSION_COOKIE,
        value=grant.raw_session,
        max_age=SESSION_COOKIE_MAX_AGE,
    )
    _set_host_cookie(
        response,
        key=CSRF_COOKIE,
        value=grant.csrf_token,
        max_age=SESSION_COOKIE_MAX_AGE,
    )
    response.delete_cookie(
        OIDC_COOKIE,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.headers["X-CSRF-Token"] = grant.csrf_token
    response.headers["Cache-Control"] = "no-store"
    return OperatorSessionResponse(
        workspace_id=grant.workspace_id,
        user_id=grant.user_id,
        membership_id=grant.membership_id,
        session_id=grant.session_id,
        expires_at=grant.expires_at,
    )


@router.post("/workspaces/{workspace_id}/session/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_operator_session(
    workspace_id: uuid.UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    raw_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    try:
        validate_csrf(csrf_cookie, csrf_header)
        if raw_session is None:
            raise InvalidSessionError("session is missing")
        async with session.begin():
            await session.execute(
                text("SELECT set_config('atlas.workspace_id', :workspace_id, TRUE)"),
                {"workspace_id": str(workspace_id)},
            )
            lifecycle = IdentityLifecycleService(session)
            identity_session = await lifecycle.authenticate_session(
                workspace_id=workspace_id,
                raw_secret=raw_session,
            )
            membership = await WorkspaceMembershipRepository(session).get_by_user(
                workspace_id=workspace_id,
                user_id=identity_session.user_id,
            )
            if membership is None or membership.status != "active":
                raise InvalidSessionError("membership is unavailable")
            await lifecycle.revoke_session(
                workspace_id=workspace_id,
                session_id=identity_session.id,
                reason="operator_logout",
            )
    except (InvalidSessionError, ValueError) as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Session revocation was denied.") from error
    _clear_operator_cookies(response)
