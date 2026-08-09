"""Authenticated IP-03 operator API for workspace-owned Gmail connections."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections import CapabilityGrant, ConnectionCreate, ConnectionService
from app.core.config import Settings, get_settings
from app.database.session import get_db_session
from app.encryption import KeyReference
from app.execution_context import ExecutionContext, ExecutionContextService
from app.identity.lifecycle import InvalidSessionError, validate_csrf
from app.integrations.gmail.credential_store import (
    GmailCredentialBindingError,
    GmailCredentialSink,
)
from app.integrations.gmail.oauth import (
    GmailOAuthConfiguration,
    GmailOAuthError,
    GmailOAuthProtocol,
)
from app.integrations.gmail.operator import (
    GmailConnectionStatusService,
    GmailConnectionView,
    GmailOperatorContextFactory,
    GmailOperatorError,
)
from app.integrations.gmail.workspace_oauth import (
    GmailAuthorizationStart,
    GmailWorkspaceOAuthService,
)
from app.integrations.google_oauth import ALLOWED_SCOPES
from app.integrations.kms import key_provider_from_settings
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.oauth_transactions import OAuthSecurityPolicy
from app.oauth_transactions.contracts import (
    OAuthAuthorizationError,
    OAuthBindingError,
    OAuthCallback,
    OAuthPurpose,
    OAuthReplayError,
    OAuthScopeError,
    parse_workspace_hint,
)
from app.oauth_transactions.service import OAuthTransactionService

router = APIRouter()


class GmailConnectRequest(BaseModel):
    provider_account_id: str = Field(min_length=3, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    operations: tuple[str, ...] = ("profile",)
    connection_id: uuid.UUID | None = None


class GmailAuthorizationResponse(BaseModel):
    connection_id: uuid.UUID
    transaction_id: uuid.UUID
    authorization_url: str
    state: str = "authorization_pending"


class GmailConnectionResponse(BaseModel):
    connection_id: uuid.UUID
    workspace_id: uuid.UUID
    provider: str
    provider_account_id: str
    state: str
    granted_scopes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None


def _configuration(settings: Settings) -> GmailOAuthConfiguration:
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    client_file = Path(settings.google_oauth_client_secret_file)
    if client_file.is_file():
        try:
            document = json.loads(client_file.read_text())
            values = document.get("web") or document.get("installed")
            client_id = str(values["client_id"])
            secret_value = str(values["client_secret"])
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Workspace Gmail OAuth configuration is invalid.",
            ) from error
    elif client_id is not None and client_secret is not None:
        secret_value = client_secret.get_secret_value()
    else:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Workspace Gmail OAuth is not configured.",
        )
    return GmailOAuthConfiguration(
        client_id=client_id,
        client_secret=secret_value,
        redirect_uri=settings.google_oauth_workspace_redirect_uri,
    )


def _key_reference(settings: Settings) -> KeyReference:
    if not settings.atlas_kms_key_resource or not settings.atlas_kms_key_version:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Managed credential encryption is not configured.",
        )
    return KeyReference(settings.atlas_kms_key_resource, settings.atlas_kms_key_version)


async def _operator_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    raw_session: str | None,
    request_id: str,
    correlation_id: str,
) -> ExecutionContext:
    if raw_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Operator session is required.")
    await session.execute(
        text("SELECT set_config('atlas.workspace_id', :workspace_id, TRUE)"),
        {"workspace_id": str(workspace_id)},
    )
    try:
        context = await GmailOperatorContextFactory(session).authenticate(
            workspace_id=workspace_id,
            raw_session=raw_session,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await ExecutionContextService().apply(session, context)
        return context
    except GmailOperatorError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error


def _oauth_service(
    session: AsyncSession,
    context: ExecutionContext,
    settings: Settings,
) -> tuple[GmailWorkspaceOAuthService, KeyReference]:
    configuration = _configuration(settings)
    key_reference = _key_reference(settings)
    keys = key_provider_from_settings(settings)
    protocol = GmailOAuthProtocol(configuration)
    sink = GmailCredentialSink(
        session,
        context,
        key_provider=keys,
        key_reference=key_reference,
    )
    transactions = OAuthTransactionService(
        session,
        context,
        policy=OAuthSecurityPolicy(
            allowed_redirect_uris=frozenset({configuration.redirect_uri}),
            allowed_issuers=frozenset({"https://accounts.google.com"}),
            allowed_scopes=frozenset(ALLOWED_SCOPES),
        ),
        key_provider=keys,
        dispatcher=protocol,
        credential_sink=sink,
    )
    return (
        GmailWorkspaceOAuthService(
            transactions=transactions,
            protocol=protocol,
            redirect_uri=configuration.redirect_uri,
            issuer="https://accounts.google.com",
        ),
        key_reference,
    )


def _capabilities(operations: tuple[str, ...]) -> tuple[CapabilityGrant, ...]:
    values = {"email.read"} if set(operations) & {"profile", "list", "unread", "search"} else set()
    if set(operations) & {"draft", "send"}:
        values.add("email.send")
    return tuple(CapabilityGrant(value) for value in sorted(values))


@router.post(
    "/workspaces/{workspace_id}/connections/oauth",
    response_model=GmailAuthorizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_gmail_connection(
    workspace_id: uuid.UUID,
    request: GmailConnectRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    atlas_session: Annotated[str | None, Cookie(alias="__Host-atlas_session")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias="__Host-atlas_csrf")] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    request_id: Annotated[str, Header(alias="X-Request-ID")] = "request",
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")] = "correlation",
) -> GmailAuthorizationResponse:
    try:
        validate_csrf(csrf_cookie, csrf_header)
    except InvalidSessionError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed.") from error
    async with session.begin():
        context = await _operator_context(
            session,
            workspace_id=workspace_id,
            raw_session=atlas_session,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        connections = ConnectionService(session, context)
        connection_id = request.connection_id or uuid.uuid4()
        purpose = OAuthPurpose.REAUTHORIZE if request.connection_id else OAuthPurpose.CONNECT
        if request.connection_id is None:
            await connections.create(
                ConnectionCreate(
                    connection_id=connection_id,
                    provider_key="google_workspace",
                    connection_kind="workspace_suite",
                    provider_account_id=request.provider_account_id.strip().lower(),
                    display_name=request.display_name,
                    capability_grants=_capabilities(request.operations),
                )
            )
        else:
            existing = await connections.get(connection_id=connection_id)
            if (
                existing.provider_account_id.strip().lower()
                != request.provider_account_id.strip().lower()
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Google account binding does not match.",
                )
        oauth, key_reference = _oauth_service(session, context, get_settings())
        started = await oauth.start(
            GmailAuthorizationStart(
                connection_id=connection_id,
                operations=request.operations,
                idempotency_key=idempotency_key,
                purpose=purpose,
            ),
            key_reference=key_reference,
        )
        return GmailAuthorizationResponse(
            connection_id=connection_id,
            transaction_id=started.transaction_id,
            authorization_url=started.authorization_url,
        )


@router.get("/connections/oauth/callback", response_model=GmailConnectionResponse)
async def complete_gmail_connection(
    state_value: Annotated[str, Query(alias="state")],
    code: str,
    scope: str,
    issuer: Annotated[str, Query(alias="iss")],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    atlas_session: Annotated[str | None, Cookie(alias="__Host-atlas_session")] = None,
    request_id: Annotated[str, Header(alias="X-Request-ID")] = "request",
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")] = "correlation",
) -> GmailConnectionResponse:
    try:
        workspace_id = parse_workspace_hint(state_value)
    except Exception as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth callback is invalid.") from error
    failure: HTTPException | None = None
    response: GmailConnectionResponse | None = None
    async with session.begin():
        context = await _operator_context(
            session,
            workspace_id=workspace_id,
            raw_session=atlas_session,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        oauth, _ = _oauth_service(session, context, get_settings())
        try:
            connection_id = await oauth.complete(
                OAuthCallback(
                    state=state_value,
                    code=code,
                    returned_scopes=tuple(scope.split()),
                    issuer=issuer,
                    redirect_uri=get_settings().google_oauth_workspace_redirect_uri,
                    received_at=datetime.now(UTC),
                )
            )
        except OAuthAuthorizationError as error:
            failure = HTTPException(
                status.HTTP_403_FORBIDDEN,
                "OAuth callback is not authorized.",
            )
            await _record_callback_failure(session, context, "authorization_denied")
            failure.__cause__ = error
        except (
            GmailCredentialBindingError,
            GmailOAuthError,
            OAuthBindingError,
            OAuthReplayError,
            OAuthScopeError,
            ValueError,
        ) as error:
            failure = HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "OAuth callback failed.",
            )
            await _record_callback_failure(
                session,
                context,
                "callback_rejected",
            )
            failure.__cause__ = error
        else:
            connection = await ConnectionService(session, context).get(
                connection_id=connection_id
            )
            response = _response(
                await GmailConnectionStatusService(session, context).get(connection)
            )
    if failure is not None:
        raise failure
    assert response is not None
    return response


@router.get(
    "/workspaces/{workspace_id}/connections/{connection_id}",
    response_model=GmailConnectionResponse,
)
async def verify_gmail_connection(
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    atlas_session: Annotated[str | None, Cookie(alias="__Host-atlas_session")] = None,
    request_id: Annotated[str, Header(alias="X-Request-ID")] = "request",
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")] = "correlation",
) -> GmailConnectionResponse:
    async with session.begin():
        context = await _operator_context(
            session,
            workspace_id=workspace_id,
            raw_session=atlas_session,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        connection = await ConnectionService(session, context).get(connection_id=connection_id)
        return _response(await GmailConnectionStatusService(session, context).get(connection))


def _response(view: GmailConnectionView) -> GmailConnectionResponse:
    return GmailConnectionResponse(
        connection_id=view.connection_id,
        workspace_id=view.workspace_id,
        provider=view.provider,
        provider_account_id=view.provider_account_id,
        state=view.state.value,
        granted_scopes=view.granted_scopes,
        created_at=view.created_at,
        updated_at=view.updated_at,
        activated_at=view.activated_at,
    )


async def _record_callback_failure(
    session: AsyncSession,
    context: ExecutionContext,
    category: str,
) -> None:
    await AuditWriterService(session, context).write(
        AuditInput(
            action="gmail.oauth_callback_failed",
            target_type="workspace",
            target_id=context.tenant.workspace_id,
            outcome="denied",
            details={"category": category, "provider": "gmail"},
        )
    )
