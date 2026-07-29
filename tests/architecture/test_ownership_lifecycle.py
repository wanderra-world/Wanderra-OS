"""Invariant matrix for the disposable H0-02 ownership prototype."""

from uuid import UUID, uuid4

import pytest

from tests.architecture.ownership_prototype import (
    InvalidClosureTransitionError,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    OrganizationType,
    OwnershipInvariantError,
    Workspace,
    WorkspaceClosure,
    WorkspaceClosureState,
    can_access_workspace_content,
)


def membership(
    role: OrganizationRole,
    *,
    user_id: UUID | None = None,
) -> OrganizationMembership:
    return OrganizationMembership(user_id=user_id or uuid4(), role=role)


def test_fit_owner_001_business_organization_requires_an_active_owner() -> None:
    """FIT-OWNER-001 rejects organizations without an active owner."""

    with pytest.raises(OwnershipInvariantError, match="active owner"):
        Organization(
            id=uuid4(),
            organization_type=OrganizationType.BUSINESS,
            memberships=(membership(OrganizationRole.ADMIN),),
        )


@pytest.mark.parametrize("operation", ["deactivate", "remove"])
def test_fit_owner_002_last_active_owner_cannot_be_lost(operation: str) -> None:
    """FIT-OWNER-002 protects the final active owner across lifecycle operations."""

    owner = membership(OrganizationRole.OWNER)
    organization = Organization(
        id=uuid4(),
        organization_type=OrganizationType.BUSINESS,
        memberships=(owner, membership(OrganizationRole.ADMIN)),
    )

    with pytest.raises(OwnershipInvariantError, match="active owner"):
        if operation == "deactivate":
            organization.deactivate_membership(owner.user_id)
        else:
            organization.remove_membership(owner.user_id)


def test_fit_owner_003_one_of_multiple_business_owners_can_be_removed() -> None:
    """FIT-OWNER-003 permits owner changes that preserve an active owner."""

    first_owner = membership(OrganizationRole.OWNER)
    second_owner = membership(OrganizationRole.OWNER)
    organization = Organization(
        id=uuid4(),
        organization_type=OrganizationType.BUSINESS,
        memberships=(first_owner, second_owner),
    )

    updated = organization.remove_membership(first_owner.user_id)

    assert updated.memberships == (second_owner,)


def test_fit_owner_004_personal_organization_is_single_member() -> None:
    """FIT-OWNER-004 keeps Personal inside the standard single-owner model."""

    personal_owner = membership(OrganizationRole.OWNER)
    personal = Organization(
        id=uuid4(),
        organization_type=OrganizationType.PERSONAL,
        memberships=(personal_owner,),
    )

    with pytest.raises(OwnershipInvariantError, match="exactly one membership"):
        personal.add_membership(membership(OrganizationRole.ADMIN))

    with pytest.raises(OwnershipInvariantError, match="active owner"):
        personal.remove_membership(personal_owner.user_id)


def test_fit_owner_005_workspace_transfer_is_prohibited() -> None:
    """FIT-OWNER-005 keeps organization ownership immutable during Phase 2."""

    organization_id = uuid4()
    workspace = Workspace(id=uuid4(), organization_id=organization_id)

    assert workspace.transfer_to(organization_id) is workspace
    with pytest.raises(OwnershipInvariantError, match="transfer is prohibited"):
        workspace.transfer_to(uuid4())


def test_fit_owner_006_organization_admin_has_no_implicit_content_access() -> None:
    """FIT-OWNER-006 requires workspace membership for content access."""

    organization_admin_id = uuid4()
    workspace_member_id = uuid4()
    workspace_members = frozenset({workspace_member_id})

    assert not can_access_workspace_content(
        organization_admin_id,
        workspace_members,
    )
    assert can_access_workspace_content(workspace_member_id, workspace_members)


def test_fit_owner_007_workspace_closure_is_ordered_and_receipted() -> None:
    """FIT-OWNER-007 proves the complete approved closure lifecycle."""

    closure = WorkspaceClosure(workspace_id=uuid4())
    closure = closure.freeze_writes("freeze-command")
    closure = closure.revoke_access("revocation-job")
    closure = closure.apply_policy("retention-evaluation")
    closure = closure.erase_eligible_data("erasure-job")
    closure = closure.verify_provider_actions("provider-verification")
    closure = closure.close("closure-receipt")

    assert closure.state is WorkspaceClosureState.CLOSED
    assert tuple(receipt.state for receipt in closure.receipts) == (
        WorkspaceClosureState.WRITES_FROZEN,
        WorkspaceClosureState.ACCESS_REVOKED,
        WorkspaceClosureState.POLICY_APPLIED,
        WorkspaceClosureState.ELIGIBLE_DATA_ERASED,
        WorkspaceClosureState.PROVIDER_ACTIONS_VERIFIED,
        WorkspaceClosureState.CLOSED,
    )
    assert closure.receipts[-1].reference == "closure-receipt"


def test_fit_owner_008_workspace_closure_rejects_skips_and_empty_receipts() -> None:
    """FIT-OWNER-008 rejects unordered or unauditable closure progress."""

    closure = WorkspaceClosure(workspace_id=uuid4())

    with pytest.raises(InvalidClosureTransitionError, match="expected"):
        closure.revoke_access("too-early")

    with pytest.raises(OwnershipInvariantError, match="receipt reference"):
        closure.freeze_writes(" ")
