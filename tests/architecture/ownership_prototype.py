"""Disposable H0 prototype for organization ownership and workspace closure."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID


class OwnershipInvariantError(ValueError):
    """Raised when an organization or workspace ownership invariant is violated."""


class InvalidClosureTransitionError(ValueError):
    """Raised when workspace closure steps are attempted out of order."""


class OrganizationType(StrEnum):
    BUSINESS = "business"
    PERSONAL = "personal"


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"


class WorkspaceClosureState(StrEnum):
    ACTIVE = "active"
    WRITES_FROZEN = "writes_frozen"
    ACCESS_REVOKED = "access_revoked"
    POLICY_APPLIED = "policy_applied"
    ELIGIBLE_DATA_ERASED = "eligible_data_erased"
    PROVIDER_ACTIONS_VERIFIED = "provider_actions_verified"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class OrganizationMembership:
    """One organization-level administrative membership."""

    user_id: UUID
    role: OrganizationRole
    active: bool = True


@dataclass(frozen=True, slots=True)
class Organization:
    """Organization aggregate constrained by the approved P0.2 invariants."""

    id: UUID
    organization_type: OrganizationType
    memberships: tuple[OrganizationMembership, ...]

    def __post_init__(self) -> None:
        user_ids = [membership.user_id for membership in self.memberships]
        if len(user_ids) != len(set(user_ids)):
            raise OwnershipInvariantError("organization memberships must be unique")

        active_memberships = tuple(
            membership for membership in self.memberships if membership.active
        )
        active_owners = tuple(
            membership
            for membership in active_memberships
            if membership.role is OrganizationRole.OWNER
        )
        if not active_owners:
            raise OwnershipInvariantError(
                "organization must retain at least one active owner"
            )

        if self.organization_type is OrganizationType.PERSONAL:
            if len(active_memberships) != 1 or len(self.memberships) != 1:
                raise OwnershipInvariantError(
                    "personal organization must have exactly one membership"
                )
            if active_memberships[0].role is not OrganizationRole.OWNER:
                raise OwnershipInvariantError(
                    "personal organization member must be its owner"
                )

    def add_membership(
        self,
        membership: OrganizationMembership,
    ) -> Organization:
        """Return a validated aggregate with one new membership."""

        return replace(self, memberships=(*self.memberships, membership))

    def deactivate_membership(self, user_id: UUID) -> Organization:
        """Deactivate a membership while preserving the active-owner invariant."""

        if not any(membership.user_id == user_id for membership in self.memberships):
            raise OwnershipInvariantError("organization membership does not exist")
        memberships = tuple(
            replace(membership, active=False)
            if membership.user_id == user_id
            else membership
            for membership in self.memberships
        )
        return replace(self, memberships=memberships)

    def remove_membership(self, user_id: UUID) -> Organization:
        """Remove a membership while preserving the active-owner invariant."""

        memberships = tuple(
            membership
            for membership in self.memberships
            if membership.user_id != user_id
        )
        if len(memberships) == len(self.memberships):
            raise OwnershipInvariantError("organization membership does not exist")
        return replace(self, memberships=memberships)


@dataclass(frozen=True, slots=True)
class Workspace:
    """Workspace with immutable organization ownership during Phase 2."""

    id: UUID
    organization_id: UUID

    def transfer_to(self, organization_id: UUID) -> Workspace:
        """Reject workspace transfer until a future ADR defines the protocol."""

        if organization_id == self.organization_id:
            return self
        raise OwnershipInvariantError("workspace transfer is prohibited in Phase 2")


@dataclass(frozen=True, slots=True)
class ClosureReceipt:
    """Evidence recorded for one completed closure transition."""

    state: WorkspaceClosureState
    reference: str

    def __post_init__(self) -> None:
        if not self.reference.strip():
            raise OwnershipInvariantError("closure receipt reference is required")


@dataclass(frozen=True, slots=True)
class WorkspaceClosure:
    """Ordered, receipted workspace-closure state machine."""

    workspace_id: UUID
    state: WorkspaceClosureState = WorkspaceClosureState.ACTIVE
    receipts: tuple[ClosureReceipt, ...] = ()

    def freeze_writes(self, reference: str) -> WorkspaceClosure:
        return self._advance(
            WorkspaceClosureState.ACTIVE,
            WorkspaceClosureState.WRITES_FROZEN,
            reference,
        )

    def revoke_access(self, reference: str) -> WorkspaceClosure:
        return self._advance(
            WorkspaceClosureState.WRITES_FROZEN,
            WorkspaceClosureState.ACCESS_REVOKED,
            reference,
        )

    def apply_policy(self, reference: str) -> WorkspaceClosure:
        return self._advance(
            WorkspaceClosureState.ACCESS_REVOKED,
            WorkspaceClosureState.POLICY_APPLIED,
            reference,
        )

    def erase_eligible_data(self, reference: str) -> WorkspaceClosure:
        return self._advance(
            WorkspaceClosureState.POLICY_APPLIED,
            WorkspaceClosureState.ELIGIBLE_DATA_ERASED,
            reference,
        )

    def verify_provider_actions(self, reference: str) -> WorkspaceClosure:
        return self._advance(
            WorkspaceClosureState.ELIGIBLE_DATA_ERASED,
            WorkspaceClosureState.PROVIDER_ACTIONS_VERIFIED,
            reference,
        )

    def close(self, reference: str) -> WorkspaceClosure:
        return self._advance(
            WorkspaceClosureState.PROVIDER_ACTIONS_VERIFIED,
            WorkspaceClosureState.CLOSED,
            reference,
        )

    def _advance(
        self,
        expected: WorkspaceClosureState,
        target: WorkspaceClosureState,
        reference: str,
    ) -> WorkspaceClosure:
        if self.state is not expected:
            raise InvalidClosureTransitionError(
                f"cannot transition from {self.state} to {target}; expected {expected}"
            )
        receipt = ClosureReceipt(state=target, reference=reference)
        return replace(self, state=target, receipts=(*self.receipts, receipt))


def can_access_workspace_content(
    user_id: UUID,
    workspace_members: frozenset[UUID],
) -> bool:
    """Prove that organization administration alone grants no content access."""

    return user_id in workspace_members
