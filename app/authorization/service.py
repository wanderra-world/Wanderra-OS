"""Deny-first H1-05 authorization service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization.contracts import (
    AuthorizationDecision,
    AuthorizationRequest,
    DecisionEffect,
    ReasonCode,
)
from app.authorization.repository import AuthorizationRepository
from app.tenancy.models import AuditEvent, OutboxEvent


class AuthorizationService:
    """Evaluate one fixed-role permission without positive-result caching."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = AuthorizationRepository(session)

    async def authorize(
        self,
        request: AuthorizationRequest,
        *,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        decided_at = now or datetime.now(UTC)
        if request.requested_workspace_id != request.membership_workspace_id:
            return await self._deny(request, ReasonCode.WORKSPACE_MISMATCH, decided_at)

        actor = await self._repository.get_actor(request.actor_id)
        if actor is None or actor.status != "active":
            return await self._deny(request, ReasonCode.INVALID_ACTOR, decided_at)

        identity_session = await self._repository.get_session(
            workspace_id=request.requested_workspace_id,
            session_id=request.session_id,
        )
        if (
            identity_session is None
            or identity_session.user_id != request.actor_id
            or identity_session.revoked_at is not None
            or identity_session.expires_at <= decided_at
        ):
            return await self._deny(request, ReasonCode.INVALID_SESSION, decided_at)

        membership = await self._repository.get_membership(
            workspace_id=request.requested_workspace_id,
            membership_id=request.membership_id,
        )
        if (
            membership is None
            or membership.user_id != request.actor_id
            or membership.organization_id != request.organization_id
            or membership.status != "active"
        ):
            return await self._deny(
                request,
                ReasonCode.INVALID_MEMBERSHIP,
                decided_at,
            )

        permission = await self._repository.get_permission(
            permission_key=request.permission_key,
            permission_version=request.permission_version,
        )
        if permission is None or not permission.active:
            return await self._deny(
                request,
                ReasonCode.UNKNOWN_PERMISSION,
                decided_at,
            )

        effects = await self._repository.list_role_permission_effects(
            role_key=membership.role_key,
            role_version=membership.role_version,
            permission_key=permission.permission_key,
            permission_version=permission.version,
        )
        if "deny" in effects:
            return await self._deny(request, ReasonCode.EXPLICIT_DENY, decided_at)
        if "allow" not in effects:
            return await self._deny(
                request,
                ReasonCode.ROLE_PERMISSION_MISSING,
                decided_at,
            )

        decision = AuthorizationDecision.allow(permission.version, now=decided_at)
        await self._record_decision(request, decision)
        return decision

    async def _deny(
        self,
        request: AuthorizationRequest,
        reason: ReasonCode,
        decided_at: datetime,
    ) -> AuthorizationDecision:
        decision = AuthorizationDecision.deny(
            reason,
            request.permission_version,
            now=decided_at,
        )
        await self._record_decision(request, decision)
        return decision

    async def _record_decision(
        self,
        request: AuthorizationRequest,
        decision: AuthorizationDecision,
    ) -> None:
        audit_id = uuid.uuid4()
        details = {
            "effect": decision.effect.value,
            "reason": decision.reason.value,
            "policy_version": decision.policy_version,
            "permission_key": request.permission_key,
            "permission_version": decision.permission_version,
            "request_reference": request.request_reference,
        }
        self._session.add(
            AuditEvent(
                workspace_id=request.requested_workspace_id,
                id=audit_id,
                actor_type="user",
                actor_id=request.actor_id,
                action="authorization.decided",
                target_type="workspace_membership",
                target_id=request.membership_id,
                outcome=(
                    "success"
                    if decision.effect is DecisionEffect.ALLOW
                    else "denied"
                ),
                details=details,
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=request.requested_workspace_id,
                id=uuid.uuid4(),
                event_type="authorization.decided",
                aggregate_type="authorization_decision",
                aggregate_id=audit_id,
                aggregate_sequence=1,
                payload={"audit_event_id": str(audit_id), **details},
            )
        )
        await self._session.flush()
