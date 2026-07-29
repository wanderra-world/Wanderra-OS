"""Entity/projection integrity matrix for the disposable H0-11 prototype."""

from uuid import uuid4

import pytest

from tests.architecture.entity_projection_prototype import (
    CapabilityService,
    CapabilityType,
    Entity,
    EntityIntegrityError,
    EntityService,
    EntityStore,
    EntityType,
    EntityTypeRegistry,
    Lifecycle,
    RelationshipService,
    RelationshipType,
)


@pytest.fixture
def store() -> EntityStore:
    return EntityStore()


@pytest.fixture
def entities(store: EntityStore) -> EntityService:
    return EntityService(store, EntityTypeRegistry())


def test_fit_entity_001_only_approved_types_are_registered() -> None:
    """FIT-ENTITY-001 excludes infrastructure and future-module records."""

    registry = EntityTypeRegistry()
    assert registry.resolve("contact").entity_type is EntityType.CONTACT
    for prohibited in (
        "organization",
        "workspace",
        "identity",
        "membership",
        "connection",
        "credential",
        "policy",
        "event",
        "audit",
        "job",
        "invoice",
        "vehicle",
    ):
        with pytest.raises(EntityIntegrityError, match="not registered"):
            registry.resolve(prohibited)


@pytest.mark.parametrize("entity_type", list(EntityType))
def test_fit_entity_002_aggregate_and_projection_are_created_atomically(
    entities: EntityService,
    entity_type: EntityType,
) -> None:
    """FIT-ENTITY-002 creates each approved aggregate with one typed projection."""

    aggregate, entity = entities.create(
        workspace_id=uuid4(),
        entity_type_name=entity_type.value,
    )

    assert entity.aggregate_id == aggregate.id
    assert entity.workspace_id == aggregate.workspace_id
    assert entity.entity_type is aggregate.entity_type
    assert entity.registry_version == 1
    assert entities.entity_for_aggregate(aggregate.id) == entity


def test_fit_entity_003_projection_failure_rolls_back_aggregate(
    store: EntityStore,
    entities: EntityService,
) -> None:
    """FIT-ENTITY-003 prevents aggregate/entity partial commits."""

    with pytest.raises(EntityIntegrityError, match="injected"):
        entities.create(
            workspace_id=uuid4(),
            entity_type_name="project",
            fail_after_aggregate=True,
        )

    assert store.aggregates == {}
    assert store.entities == {}


def test_fit_entity_004_direct_registry_insertion_is_prohibited(
    store: EntityStore,
) -> None:
    """FIT-ENTITY-004 requires entity creation through the owning aggregate."""

    with pytest.raises(EntityIntegrityError, match="direct"):
        store.direct_insert_entity(
            Entity(
                id=uuid4(),
                workspace_id=uuid4(),
                entity_type=EntityType.PROJECT,
                aggregate_id=uuid4(),
                registry_version=1,
            )
        )


def test_fit_entity_005_exactly_one_active_projection_is_enforced(
    store: EntityStore,
    entities: EntityService,
) -> None:
    """FIT-ENTITY-005 detects a missing or duplicated typed projection."""

    aggregate, entity = entities.create(
        workspace_id=uuid4(),
        entity_type_name="project",
    )
    store.entities[uuid4()] = Entity(
        id=uuid4(),
        workspace_id=entity.workspace_id,
        entity_type=entity.entity_type,
        aggregate_id=aggregate.id,
        registry_version=1,
    )

    with pytest.raises(EntityIntegrityError, match="exactly one"):
        entities.entity_for_aggregate(aggregate.id)


def create_entity(
    entities: EntityService,
    workspace_id,
    entity_type: EntityType,
) -> Entity:
    return entities.create(
        workspace_id=workspace_id,
        entity_type_name=entity_type.value,
    )[1]


def test_fit_entity_006_relationship_validates_type_and_direction(
    store: EntityStore,
    entities: EntityService,
) -> None:
    """FIT-ENTITY-006 rejects wrong endpoint types and reversed direction."""

    workspace_id = uuid4()
    project = create_entity(entities, workspace_id, EntityType.PROJECT)
    task = create_entity(entities, workspace_id, EntityType.TASK)
    relationships = RelationshipService(store)

    relationships.create(
        relationship_type=RelationshipType.PROJECT_HAS_TASK,
        source_entity_id=project.id,
        target_entity_id=task.id,
    )
    with pytest.raises(EntityIntegrityError, match="type or direction"):
        relationships.create(
            relationship_type=RelationshipType.PROJECT_HAS_TASK,
            source_entity_id=task.id,
            target_entity_id=project.id,
        )


def test_fit_entity_007_cross_workspace_relationship_is_rejected(
    store: EntityStore,
    entities: EntityService,
) -> None:
    """FIT-ENTITY-007 defers all cross-workspace relationships."""

    project = create_entity(entities, uuid4(), EntityType.PROJECT)
    task = create_entity(entities, uuid4(), EntityType.TASK)

    with pytest.raises(EntityIntegrityError, match="cross-workspace"):
        RelationshipService(store).create(
            relationship_type=RelationshipType.PROJECT_HAS_TASK,
            source_entity_id=project.id,
            target_entity_id=task.id,
        )


def test_fit_entity_008_relationship_cardinality_is_enforced(
    store: EntityStore,
    entities: EntityService,
) -> None:
    """FIT-ENTITY-008 enforces the registered maximum per source."""

    workspace_id = uuid4()
    contact = create_entity(entities, workspace_id, EntityType.CONTACT)
    first_company = create_entity(entities, workspace_id, EntityType.COMPANY)
    second_company = create_entity(entities, workspace_id, EntityType.COMPANY)
    relationships = RelationshipService(store)
    relationships.create(
        relationship_type=RelationshipType.CONTACT_WORKS_FOR_COMPANY,
        source_entity_id=contact.id,
        target_entity_id=first_company.id,
    )

    with pytest.raises(EntityIntegrityError, match="cardinality"):
        relationships.create(
            relationship_type=RelationshipType.CONTACT_WORKS_FOR_COMPANY,
            source_entity_id=contact.id,
            target_entity_id=second_company.id,
        )


def test_fit_entity_009_relationship_requires_active_endpoints(
    store: EntityStore,
    entities: EntityService,
) -> None:
    """FIT-ENTITY-009 prevents relationships to deleted entities."""

    workspace_id = uuid4()
    project_aggregate, project = entities.create(
        workspace_id=workspace_id,
        entity_type_name="project",
    )
    task = create_entity(entities, workspace_id, EntityType.TASK)
    entities.delete(project_aggregate.id)

    with pytest.raises(EntityIntegrityError, match="must be active"):
        RelationshipService(store).create(
            relationship_type=RelationshipType.PROJECT_HAS_TASK,
            source_entity_id=project.id,
            target_entity_id=task.id,
        )


@pytest.mark.parametrize("capability_type", list(CapabilityType))
def test_fit_entity_010_generic_capabilities_attach_to_active_entity(
    store: EntityStore,
    entities: EntityService,
    capability_type: CapabilityType,
) -> None:
    """FIT-ENTITY-010 supports governed generic capabilities without new entities."""

    workspace_id = uuid4()
    entity = create_entity(entities, workspace_id, EntityType.DOCUMENT)
    capability = CapabilityService(store).attach(
        workspace_id=workspace_id,
        entity_id=entity.id,
        capability_type=capability_type,
    )

    assert capability.entity_id == entity.id
    assert capability.workspace_id == workspace_id


def test_fit_entity_011_deletion_starts_at_owner_and_cascades_lifecycle(
    store: EntityStore,
    entities: EntityService,
) -> None:
    """FIT-ENTITY-011 applies deletion to projection, relationships, and capabilities."""

    workspace_id = uuid4()
    project_aggregate, project = entities.create(
        workspace_id=workspace_id,
        entity_type_name="project",
    )
    task = create_entity(entities, workspace_id, EntityType.TASK)
    relationship = RelationshipService(store).create(
        relationship_type=RelationshipType.PROJECT_HAS_TASK,
        source_entity_id=project.id,
        target_entity_id=task.id,
    )
    capability = CapabilityService(store).attach(
        workspace_id=workspace_id,
        entity_id=project.id,
        capability_type=CapabilityType.TAG,
    )

    deleted_aggregate, deleted_entity = entities.delete(project_aggregate.id)

    assert deleted_aggregate.lifecycle is Lifecycle.DELETED
    assert deleted_entity.lifecycle is Lifecycle.DELETED
    assert store.relationships[relationship.id].lifecycle is Lifecycle.DELETED
    assert store.capabilities[capability.id].lifecycle is Lifecycle.DELETED


def test_fit_entity_012_type_change_requires_explicit_migration(
    entities: EntityService,
) -> None:
    """FIT-ENTITY-012 prohibits runtime mutation of entity type."""

    aggregate, _ = entities.create(
        workspace_id=uuid4(),
        entity_type_name="communication",
    )
    with pytest.raises(EntityIntegrityError, match="require migrations"):
        entities.change_entity_type_directly(aggregate.id, EntityType.DOCUMENT)
    with pytest.raises(EntityIntegrityError, match="migration reference"):
        entities.migrate_entity_type(
            aggregate.id,
            target_type_name="document",
            migration_reference="",
        )

    migrated_aggregate, migrated_entity = entities.migrate_entity_type(
        aggregate.id,
        target_type_name="document",
        migration_reference="migration-entity-001",
    )
    assert migrated_aggregate.entity_type is EntityType.DOCUMENT
    assert migrated_entity.entity_type is EntityType.DOCUMENT
