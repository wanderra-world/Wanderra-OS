"""Provider-neutral membership lifecycle contracts."""

from __future__ import annotations

from dataclasses import dataclass

MEMBERSHIP_ROLE_VERSION = 1
FIXED_MEMBERSHIP_ROLES = frozenset(
    {
        "organization_owner",
        "organization_admin",
        "workspace_owner",
        "workspace_admin",
        "member",
        "viewer",
    }
)
WORKSPACE_MEMBERSHIP_ROLES = frozenset(
    {
        "workspace_owner",
        "workspace_admin",
        "member",
        "viewer",
    }
)
MEMBERSHIP_STATUSES = frozenset({"invited", "active", "suspended", "revoked"})


class MembershipLifecycleError(ValueError):
    """Raised when a membership lifecycle transition is denied."""


@dataclass(frozen=True, slots=True)
class FixedRoleDefinition:
    """Versioned classification only; H1-05 owns authorization semantics."""

    key: str
    scope: str
    version: int = MEMBERSHIP_ROLE_VERSION


FIXED_ROLE_DEFINITIONS = tuple(
    FixedRoleDefinition(key, "organization" if key.startswith("organization_") else "workspace")
    for key in sorted(FIXED_MEMBERSHIP_ROLES)
)
