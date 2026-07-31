"""Shared provider-neutral capability routing primitives."""

from app.capability_routing.contracts import (
    AuthorizationGate,
    CapabilityRoute,
    MutationGuard,
)

__all__ = ["AuthorizationGate", "CapabilityRoute", "MutationGuard"]
