"""Disposable H0 prototype for universal entity and projection integrity."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID, uuid4


class EntityIntegrityError(ValueError):
    """Raised when an entity, projection, or relationship invariant fails."""


class EntityType(StrEnum):
    CONTACT = "contact"
    COMPANY = "company"
    PROJECT = "project"
    TASK = "task"
    COMMUNICATION = "communication"
    MEETING = "meeting"
    DOCUMENT = "document"


class Lifecycle(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class RelationshipType(StrEnum):
    CONTACT_WORKS_FOR_COMPANY = "contact_works_for_company"
    PROJECT_HAS_TASK = "project_has_task"
    DOCUMENT_ATTACHED_TO_PROJECT = "document_attached_to_project"


class CapabilityType(StrEnum):
    TAG = "tag"
    ATTACHMENT = "attachment"
    AI_NOTE = "ai_note"
    OWNERSHIP = "ownership"


@dataclass(frozen=True, slots=True)
class EntityTypeDefinition:
    entity_type: EntityType
    registry_version: int


ENTITY_TYPES: Final = MappingProxyType(
    {
        entity_type.value: EntityTypeDefinition(
            entity_type=entity_type,
            registry_version=1,
        )
        for entity_type in EntityType
    }
)


class EntityTypeRegistry:
    """Versioned Atlas-controlled registry; arbitrary types cannot be created."""

    def resolve(self, name: str) -> EntityTypeDefinition:
        try:
            return ENTITY_TYPES[name]
        except KeyError as error:
            raise EntityIntegrityError("entity type is not registered") from error


@dataclass(frozen=True, slots=True)
class TypedAggregate:
    id: UUID
    workspace_id: UUID
    entity_type: EntityType
    lifecycle: Lifecycle = Lifecycle.ACTIVE


@dataclass(frozen=True, slots=True)
class Entity:
    id: UUID
    workspace_id: UUID
    entity_type: EntityType
    aggregate_id: UUID
    registry_version: int
    lifecycle: Lifecycle = Lifecycle.ACTIVE


@dataclass(frozen=True, slots=True)
class RelationshipDefinition:
    source_type: EntityType
    target_type: EntityType
    maximum_per_source: int | None


RELATIONSHIP_DEFINITIONS: Final = MappingProxyType(
    {
        RelationshipType.CONTACT_WORKS_FOR_COMPANY: RelationshipDefinition(
            source_type=EntityType.CONTACT,
            target_type=EntityType.COMPANY,
            maximum_per_source=1,
        ),
        RelationshipType.PROJECT_HAS_TASK: RelationshipDefinition(
            source_type=EntityType.PROJECT,
            target_type=EntityType.TASK,
            maximum_per_source=None,
        ),
        RelationshipType.DOCUMENT_ATTACHED_TO_PROJECT: RelationshipDefinition(
            source_type=EntityType.DOCUMENT,
            target_type=EntityType.PROJECT,
            maximum_per_source=1,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class Relationship:
    id: UUID
    workspace_id: UUID
    relationship_type: RelationshipType
    source_entity_id: UUID
    target_entity_id: UUID
    lifecycle: Lifecycle = Lifecycle.ACTIVE


@dataclass(frozen=True, slots=True)
class GenericCapability:
    id: UUID
    workspace_id: UUID
    entity_id: UUID
    capability_type: CapabilityType
    lifecycle: Lifecycle = Lifecycle.ACTIVE


class EntityStore:
    """Transactional in-memory evidence store for the disposable prototype."""

    def __init__(self) -> None:
        self.aggregates: dict[UUID, TypedAggregate] = {}
        self.entities: dict[UUID, Entity] = {}
        self.relationships: dict[UUID, Relationship] = {}
        self.capabilities: dict[UUID, GenericCapability] = {}

    @contextmanager
    def transaction(self) -> Iterator[None]:
        snapshot = deepcopy(
            (
                self.aggregates,
                self.entities,
                self.relationships,
                self.capabilities,
            )
        )
        try:
            yield
        except Exception:
            (
                self.aggregates,
                self.entities,
                self.relationships,
                self.capabilities,
            ) = snapshot
            raise

    def direct_insert_entity(self, _entity: Entity) -> None:
        raise EntityIntegrityError("direct entity registry insertion is prohibited")


class EntityService:
    """Owning aggregate service for atomic projection and lifecycle changes."""

    def __init__(
        self,
        store: EntityStore,
        type_registry: EntityTypeRegistry,
    ) -> None:
        self._store = store
        self._type_registry = type_registry

    def create(
        self,
        *,
        workspace_id: UUID,
        entity_type_name: str,
        fail_after_aggregate: bool = False,
    ) -> tuple[TypedAggregate, Entity]:
        definition = self._type_registry.resolve(entity_type_name)
        aggregate = TypedAggregate(
            id=uuid4(),
            workspace_id=workspace_id,
            entity_type=definition.entity_type,
        )
        entity = Entity(
            id=uuid4(),
            workspace_id=workspace_id,
            entity_type=definition.entity_type,
            aggregate_id=aggregate.id,
            registry_version=definition.registry_version,
        )
        with self._store.transaction():
            self._store.aggregates[aggregate.id] = aggregate
            if fail_after_aggregate:
                raise EntityIntegrityError("injected projection creation failure")
            self._insert_projection(entity)
        return aggregate, entity

    def delete(self, aggregate_id: UUID) -> tuple[TypedAggregate, Entity]:
        aggregate = self._store.aggregates[aggregate_id]
        if aggregate.lifecycle is Lifecycle.DELETED:
            raise EntityIntegrityError("aggregate is already deleted")
        entity = self.entity_for_aggregate(aggregate_id)
        with self._store.transaction():
            deleted_aggregate = replace(aggregate, lifecycle=Lifecycle.DELETED)
            deleted_entity = replace(entity, lifecycle=Lifecycle.DELETED)
            self._store.aggregates[aggregate_id] = deleted_aggregate
            self._store.entities[entity.id] = deleted_entity
            for relationship_id, relationship in tuple(
                self._store.relationships.items()
            ):
                if entity.id in {
                    relationship.source_entity_id,
                    relationship.target_entity_id,
                }:
                    self._store.relationships[relationship_id] = replace(
                        relationship,
                        lifecycle=Lifecycle.DELETED,
                    )
            for capability_id, capability in tuple(self._store.capabilities.items()):
                if capability.entity_id == entity.id:
                    self._store.capabilities[capability_id] = replace(
                        capability,
                        lifecycle=Lifecycle.DELETED,
                    )
        return deleted_aggregate, deleted_entity

    def migrate_entity_type(
        self,
        aggregate_id: UUID,
        *,
        target_type_name: str,
        migration_reference: str,
    ) -> tuple[TypedAggregate, Entity]:
        if not migration_reference.strip():
            raise EntityIntegrityError("entity type change requires migration reference")
        definition = self._type_registry.resolve(target_type_name)
        aggregate = self._store.aggregates[aggregate_id]
        entity = self.entity_for_aggregate(aggregate_id)
        migrated_aggregate = replace(
            aggregate,
            entity_type=definition.entity_type,
        )
        migrated_entity = replace(
            entity,
            entity_type=definition.entity_type,
            registry_version=definition.registry_version,
        )
        with self._store.transaction():
            self._store.aggregates[aggregate_id] = migrated_aggregate
            self._store.entities[entity.id] = migrated_entity
        return migrated_aggregate, migrated_entity

    def change_entity_type_directly(
        self,
        _aggregate_id: UUID,
        _target_type: EntityType,
    ) -> None:
        raise EntityIntegrityError("entity type changes require migrations")

    def entity_for_aggregate(self, aggregate_id: UUID) -> Entity:
        projections = tuple(
            entity
            for entity in self._store.entities.values()
            if entity.aggregate_id == aggregate_id
            and entity.lifecycle is Lifecycle.ACTIVE
        )
        if len(projections) != 1:
            raise EntityIntegrityError(
                "aggregate must have exactly one active typed projection"
            )
        return projections[0]

    def _insert_projection(self, entity: Entity) -> None:
        aggregate = self._store.aggregates.get(entity.aggregate_id)
        if aggregate is None:
            raise EntityIntegrityError("typed aggregate must exist before projection")
        if (
            aggregate.workspace_id != entity.workspace_id
            or aggregate.entity_type is not entity.entity_type
        ):
            raise EntityIntegrityError("entity projection does not match aggregate")
        if any(
            existing.aggregate_id == entity.aggregate_id
            and existing.lifecycle is Lifecycle.ACTIVE
            for existing in self._store.entities.values()
        ):
            raise EntityIntegrityError(
                "aggregate already has an active typed projection"
            )
        self._store.entities[entity.id] = entity


class RelationshipService:
    """Validates type, direction, workspace, cardinality, and lifecycle."""

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    def create(
        self,
        *,
        relationship_type: RelationshipType,
        source_entity_id: UUID,
        target_entity_id: UUID,
    ) -> Relationship:
        source = self._store.entities[source_entity_id]
        target = self._store.entities[target_entity_id]
        definition = RELATIONSHIP_DEFINITIONS[relationship_type]
        if source.lifecycle is not Lifecycle.ACTIVE or target.lifecycle is not Lifecycle.ACTIVE:
            raise EntityIntegrityError("relationship endpoints must be active")
        if source.workspace_id != target.workspace_id:
            raise EntityIntegrityError("cross-workspace relationships are prohibited")
        if (
            source.entity_type is not definition.source_type
            or target.entity_type is not definition.target_type
        ):
            raise EntityIntegrityError("relationship endpoint type or direction is invalid")
        current = tuple(
            relationship
            for relationship in self._store.relationships.values()
            if relationship.relationship_type is relationship_type
            and relationship.source_entity_id == source.id
            and relationship.lifecycle is Lifecycle.ACTIVE
        )
        if (
            definition.maximum_per_source is not None
            and len(current) >= definition.maximum_per_source
        ):
            raise EntityIntegrityError("relationship cardinality would be exceeded")
        relationship = Relationship(
            id=uuid4(),
            workspace_id=source.workspace_id,
            relationship_type=relationship_type,
            source_entity_id=source.id,
            target_entity_id=target.id,
        )
        self._store.relationships[relationship.id] = relationship
        return relationship


class CapabilityService:
    """Attaches generic capabilities only to active same-workspace entities."""

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    def attach(
        self,
        *,
        workspace_id: UUID,
        entity_id: UUID,
        capability_type: CapabilityType,
    ) -> GenericCapability:
        entity = self._store.entities[entity_id]
        if entity.workspace_id != workspace_id:
            raise EntityIntegrityError("capability workspace does not match entity")
        if entity.lifecycle is not Lifecycle.ACTIVE:
            raise EntityIntegrityError("capability requires active entity")
        capability = GenericCapability(
            id=uuid4(),
            workspace_id=workspace_id,
            entity_id=entity_id,
            capability_type=capability_type,
        )
        self._store.capabilities[capability.id] = capability
        return capability
