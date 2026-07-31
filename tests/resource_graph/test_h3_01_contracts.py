"""Unit acceptance tests for the constrained H3-01 Resource Graph."""

from uuid import uuid4

import pytest

from app.resource_graph.contracts import (
    RelationshipKind,
    ResourceConcurrencyError,
    ResourceCreate,
    ResourceGraphError,
    ResourceKind,
    ResourceRelationshipCreate,
    require_expected_version,
    validate_relationship,
)


def test_only_architecture_approved_resource_types_exist() -> None:
    assert {kind.value for kind in ResourceKind} == {
        "contact",
        "company",
        "project",
        "task",
        "communication",
        "meeting",
        "document",
    }
    with pytest.raises(ValueError):
        ResourceCreate(resource_id=uuid4(), projection_id=uuid4(), kind="invoice")


def test_resource_create_binds_identity_to_same_typed_projection() -> None:
    command = ResourceCreate(
        resource_id=uuid4(),
        projection_id=uuid4(),
        kind=ResourceKind.PROJECT,
    )
    assert command.kind is ResourceKind.PROJECT
    assert command.resource_id != command.projection_id


def test_relationship_contract_enforces_direction_and_endpoint_types() -> None:
    validate_relationship(
        ResourceRelationshipCreate(
            relationship_id=uuid4(),
            kind=RelationshipKind.PROJECT_HAS_TASK,
            source_resource_id=uuid4(),
            target_resource_id=uuid4(),
        ),
        source_kind=ResourceKind.PROJECT,
        target_kind=ResourceKind.TASK,
    )
    with pytest.raises(ResourceGraphError, match="endpoint types"):
        validate_relationship(
            ResourceRelationshipCreate(
                relationship_id=uuid4(),
                kind=RelationshipKind.PROJECT_HAS_TASK,
                source_resource_id=uuid4(),
                target_resource_id=uuid4(),
            ),
            source_kind=ResourceKind.TASK,
            target_kind=ResourceKind.PROJECT,
        )


def test_self_relationship_and_stale_versions_fail_closed() -> None:
    resource_id = uuid4()
    with pytest.raises(ResourceGraphError, match="itself"):
        ResourceRelationshipCreate(
            relationship_id=uuid4(),
            kind=RelationshipKind.PROJECT_HAS_TASK,
            source_resource_id=resource_id,
            target_resource_id=resource_id,
        )
    with pytest.raises(ResourceConcurrencyError, match="precondition"):
        require_expected_version(current=2, expected=1)
