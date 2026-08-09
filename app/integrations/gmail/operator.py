"""IP-03 authenticated operator lifecycle over the accepted Gmail OAuth boundary."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connection_credentials.repository import ConnectionCredentialRepository
from app.connections.models import Connection
from app.execution_context import (
    ActorContext,
    ExecutionContext,
    RequestContext,
    TenantContext,
)
from app.identity.lifecycle import IdentityLifecycleService, InvalidSessionError
from app.memberships.repository import WorkspaceMembershipRepository
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.oauth_transactions.models import OAuthTransaction
from app.tenancy.models import Workspace


class GmailOperatorError(RuntimeError):
    """Safe operator-boundary failure without secret material."""


class GmailConnectionState(StrEnum):
    INITIATED = "initiated"
    AUTHORIZATION_PENDING = "authorization_pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    DISABLED = "disabled"
    EXPIRED = "expired"
    INVALID = "invalid"
    MISMATCHED = "mismatched"


@dataclass(frozen=True, slots=True)
class GmailConnectionView:
    connection_id: uuid.UUID
    workspace_id: uuid.UUID
    provider: str
    provider_account_id: str
    state: GmailConnectionState
    granted_scopes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None


class GmailOperatorContextFactory:
    """Authenticate an opaque session and construct canonical workspace context."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def authenticate(
        self,
        *,
        workspace_id: uuid.UUID,
        raw_session: str,
        request_id: str,
        correlation_id: str,
        now: datetime | None = None,
    ) -> ExecutionContext:
        try:
            identity = await IdentityLifecycleService(self._session).authenticate_session(
                workspace_id=workspace_id,
                raw_secret=raw_session,
                now=now,
            )
        except (InvalidSessionError, ValueError) as error:
            raise GmailOperatorError("operator session is invalid") from error
        membership = await WorkspaceMembershipRepository(self._session).get_by_user(
            workspace_id=workspace_id,
            user_id=identity.user_id,
        )
        workspace = await self._session.get(Workspace, workspace_id)
        if (
            membership is None
            or membership.status != "active"
            or workspace is None
            or workspace.status != "active"
        ):
            raise GmailOperatorError("operator workspace access is unavailable")
        return ExecutionContext(
            request=RequestContext(request_id, correlation_id),
            actor=ActorContext(
                actor_id=identity.user_id,
                session_id=identity.id,
                membership_id=membership.id,
                authorization_decision_id=uuid.uuid4(),
            ),
            tenant=TenantContext(
                organization_id=workspace.organization_id,
                workspace_id=workspace.id,
                cell_id=workspace.cell_id,
            ),
        )


class GmailConnectionStatusService:
    """Return only non-secret lifecycle metadata within one execution context."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
    ) -> None:
        self._session = session
        self._context = context
        self._credentials = ConnectionCredentialRepository(session, context)
        self._audit = AuditWriterService(session, context)

    async def get(
        self,
        connection: Connection,
        *,
        now: datetime | None = None,
    ) -> GmailConnectionView:
        if connection.workspace_id != self._context.tenant.workspace_id:
            raise GmailOperatorError("Gmail connection is unavailable")
        if connection.provider_key != "google_workspace":
            raise GmailOperatorError("Gmail provider binding does not match")
        checked_at = now or datetime.now(UTC)
        credential = await self._credentials.latest_generation(
            connection.id, "oauth_refresh_token"
        )
        transaction = await self._session.scalar(
            select(OAuthTransaction)
            .where(
                OAuthTransaction.workspace_id == self._context.tenant.workspace_id,
                OAuthTransaction.connection_id == connection.id,
            )
            .order_by(OAuthTransaction.created_at.desc())
            .limit(1)
        )
        state = self._state(connection, credential, transaction, checked_at)
        await self._audit.write(
            AuditInput(
                action="gmail.connection_state_read",
                target_type="connection",
                target_id=connection.id,
                outcome="succeeded",
                details={"state": state.value, "provider": "gmail"},
            )
        )
        return GmailConnectionView(
            connection_id=connection.id,
            workspace_id=connection.workspace_id,
            provider="gmail",
            provider_account_id=connection.provider_account_id,
            state=state,
            granted_scopes=tuple(sorted(connection.granted_scopes)),
            created_at=connection.created_at,
            updated_at=connection.updated_at,
            activated_at=connection.activated_at,
        )

    @staticmethod
    def _state(connection, credential, transaction, now: datetime) -> GmailConnectionState:
        if connection.status == "revoked":
            return GmailConnectionState.REVOKED
        if connection.status == "closed" or (
            credential is not None and credential.status == "disabled"
        ):
            return GmailConnectionState.DISABLED
        if transaction is not None and transaction.failure_code == "binding_mismatch":
            return GmailConnectionState.MISMATCHED
        if transaction is not None and (
            transaction.status == "expired"
            or (transaction.status == "pending" and transaction.expires_at <= now)
        ):
            return GmailConnectionState.EXPIRED
        if connection.status == "reauthorization_required" or (
            credential is not None
            and credential.status == "reauthorization_required"
        ):
            return GmailConnectionState.INVALID
        if (
            connection.status == "active"
            and credential is not None
            and credential.status == "active"
        ):
            return GmailConnectionState.ACTIVE
        if (
            transaction is not None
            and transaction.status == "pending"
            and transaction.expires_at > now
        ):
            return GmailConnectionState.AUTHORIZATION_PENDING
        if transaction is not None and transaction.status in {"failed", "cancelled"}:
            return GmailConnectionState.INVALID
        return GmailConnectionState.INITIATED
