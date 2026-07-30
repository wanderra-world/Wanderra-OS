"""Deterministic fixed-role authorization boundary for H1-05."""

from app.authorization.contracts import (
    AUTHORIZATION_POLICY_VERSION,
    AuthorizationDecision,
    AuthorizationRequest,
    DecisionEffect,
    ReasonCode,
)
from app.authorization.models import Permission, RolePermission
from app.authorization.repository import AuthorizationRepository
from app.authorization.service import AuthorizationService

__all__ = [
    "AUTHORIZATION_POLICY_VERSION",
    "AuthorizationDecision",
    "AuthorizationRepository",
    "AuthorizationRequest",
    "AuthorizationService",
    "DecisionEffect",
    "Permission",
    "ReasonCode",
    "RolePermission",
]
