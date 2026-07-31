"""Typed public contracts for the constrained H3-01 Resource Graph."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class ResourceGraphError(ValueError):
    """Raised when a Resource Graph invariant is violated."""


class ResourceGraphAuthorizationError(PermissionError):
    """Raised before Resource Graph access when authorization denies it."""


class ResourceConcurrencyError(RuntimeError):
    """Raised when an optimistic version precondition is stale."""


class ResourceKind(StrEnum):
    CONTACT = "contact"
    COMPANY = "company"
    PROJECT = "project"
    TASK = "task"
    COMMUNICATION = "communication"
    MEETING = "meeting"
    DOCUMENT = "document"


class RelationshipKind(StrEnum):
    CONTACT_WORKS_FOR_COMPANY = "contact_works_for_company"
    PROJECT_HAS_TASK = "project_has_task"
    DOCUMENT_ATTACHED_TO_PROJECT = "document_attached_to_project"
    COMMUNICATION_RELATES_TO_PROJECT = "communication_relates_to_project"
    MEETING_RELATES_TO_PROJECT = "meeting_relates_to_project"


class NoteKind(StrEnum):
    HUMAN = "human"
    AI = "ai"


@dataclass(frozen=True, slots=True)
class RelationshipDefinition:
    source_kind: ResourceKind
    target_kind: ResourceKind
    maximum_per_source: int | None = None


RELATIONSHIP_DEFINITIONS: Final = MappingProxyType(
    {
        RelationshipKind.CONTACT_WORKS_FOR_COMPANY: RelationshipDefinition(
            ResourceKind.CONTACT, ResourceKind.COMPANY, 1
        ),
        RelationshipKind.PROJECT_HAS_TASK: RelationshipDefinition(
            ResourceKind.PROJECT, ResourceKind.TASK
        ),
        RelationshipKind.DOCUMENT_ATTACHED_TO_PROJECT: RelationshipDefinition(
            ResourceKind.DOCUMENT, ResourceKind.PROJECT, 1
        ),
        RelationshipKind.COMMUNICATION_RELATES_TO_PROJECT: RelationshipDefinition(
            ResourceKind.COMMUNICATION, ResourceKind.PROJECT
        ),
        RelationshipKind.MEETING_RELATES_TO_PROJECT: RelationshipDefinition(
            ResourceKind.MEETING, ResourceKind.PROJECT
        ),
    }
)


@dataclass(frozen=True, slots=True)
class ResourceCreate:
    resource_id: uuid.UUID
    projection_id: uuid.UUID
    kind: ResourceKind

    def __post_init__(self) -> None:
        try:
            kind = ResourceKind(self.kind)
        except ValueError as error:
            raise ValueError("resource type is not registered") from error
        object.__setattr__(self, "kind", kind)
        if self.resource_id == self.projection_id:
            raise ResourceGraphError("resource and projection identities must differ")


@dataclass(frozen=True, slots=True)
class ResourceRelationshipCreate:
    relationship_id: uuid.UUID
    kind: RelationshipKind
    source_resource_id: uuid.UUID
    target_resource_id: uuid.UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", RelationshipKind(self.kind))
        if self.source_resource_id == self.target_resource_id:
            raise ResourceGraphError("a resource cannot relate to itself")


def validate_relationship(
    command: ResourceRelationshipCreate,
    *,
    source_kind: ResourceKind,
    target_kind: ResourceKind,
) -> None:
    source_kind = ResourceKind(source_kind)
    target_kind = ResourceKind(target_kind)
    definition = RELATIONSHIP_DEFINITIONS[command.kind]
    if (source_kind, target_kind) != (
        definition.source_kind,
        definition.target_kind,
    ):
        raise ResourceGraphError("relationship endpoint types or direction are invalid")


def require_expected_version(*, current: int, expected: int) -> None:
    if current != expected:
        raise ResourceConcurrencyError("resource version precondition failed")
