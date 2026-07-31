"""Authorized transactional service for the H3-01 Resource Graph."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import AuthorizationRequest, AuthorizationService, DecisionEffect
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.resource_graph.contracts import (
    RELATIONSHIP_DEFINITIONS,
    NoteKind,
    ResourceCreate,
    ResourceGraphAuthorizationError,
    ResourceGraphError,
    ResourceRelationshipCreate,
    require_expected_version,
    validate_relationship,
)
from app.resource_graph.models import (
    Resource,
    ResourceAttachment,
    ResourceExternalLink,
    ResourceGrant,
    ResourceNote,
    ResourceOwnership,
    ResourceProjection,
    ResourceRelationship,
    ResourceTag,
)
from app.resource_graph.repository import ResourceGraphRepository
from app.tenancy.models import OutboxEvent


class ResourceAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class H1ResourceAuthorizer:
    def __init__(self, session: AsyncSession) -> None:
        self._service = AuthorizationService(session)

    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool:
        decision = await self._service.authorize(
            AuthorizationRequest(
                actor_id=context.actor.actor_id,
                session_id=context.actor.session_id,
                organization_id=context.tenant.organization_id,
                requested_workspace_id=context.tenant.workspace_id,
                membership_workspace_id=context.tenant.workspace_id,
                membership_id=context.actor.membership_id,
                permission_key=permission_key,
                request_reference=context.request.request_id,
            )
        )
        return decision.effect is DecisionEffect.ALLOW


class ResourceGraphService:
    """Mutate resources inside the caller-owned execution-context transaction."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: ResourceAuthorizer | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._repository = ResourceGraphRepository(session, context)
        self._authorizer = authorizer or H1ResourceAuthorizer(session)
        self._audit = AuditWriterService(session, context)

    def _tenant(self) -> dict[str, uuid.UUID]:
        return {
            "organization_id": self._context.tenant.organization_id,
            "workspace_id": self._context.tenant.workspace_id,
            "cell_id": self._context.tenant.cell_id,
        }

    async def create(self, command: ResourceCreate, *, now: datetime | None = None) -> Resource:
        await self._require_authorized("update_content")
        created_at = now or datetime.now(UTC)
        tenant = self._tenant()
        projection = ResourceProjection(
            **tenant,
            id=command.projection_id,
            resource_id=command.resource_id,
            resource_type=command.kind.value,
            created_at=created_at,
        )
        resource = Resource(
            **tenant,
            id=command.resource_id,
            resource_type=command.kind.value,
            projection_id=command.projection_id,
            status="active",
            version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=created_at,
            updated_at=created_at,
        )
        await self._repository.add_resource_pair(projection, resource)
        await self._record(resource, "resource.created", now=created_at)
        return resource

    async def get(self, resource_id: uuid.UUID) -> Resource:
        if not await self._is_authorized("read_content", resource_id=resource_id):
            raise ResourceGraphAuthorizationError("resource read is denied")
        resource = await self._require_resource(resource_id)
        if resource.status != "active":
            raise ResourceGraphError("resource does not exist")
        return resource

    async def relate(
        self,
        command: ResourceRelationshipCreate,
        *,
        expected_source_version: int,
        now: datetime | None = None,
    ) -> ResourceRelationship:
        await self._require_authorized("update_content")
        source = await self._require_resource(command.source_resource_id, for_update=True)
        target = await self._require_resource(command.target_resource_id)
        require_expected_version(current=source.version, expected=expected_source_version)
        validate_relationship(
            command,
            source_kind=source.resource_type,
            target_kind=target.resource_type,
        )
        definition = RELATIONSHIP_DEFINITIONS[command.kind]
        if definition.maximum_per_source is not None:
            count = await self._repository.active_relationship_count(
                relationship_type=command.kind.value,
                source_resource_id=source.id,
            )
            if count >= definition.maximum_per_source:
                raise ResourceGraphError("relationship cardinality is exceeded")
        created_at = now or datetime.now(UTC)
        relationship = ResourceRelationship(
            **self._tenant(),
            id=command.relationship_id,
            relationship_type=command.kind.value,
            source_resource_id=source.id,
            target_resource_id=target.id,
            status="active",
            version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=created_at,
        )
        await self._repository.add_feature(relationship)
        source.version += 1
        source.updated_at = created_at
        await self._record(source, "resource.relationship_created", now=created_at)
        return relationship

    async def add_tag(
        self, *, resource_id: uuid.UUID, tag: str, expected_version: int
    ) -> ResourceTag:
        resource = await self._mutable(resource_id, expected_version)
        normalized = tag.strip().lower()
        if not normalized or len(normalized) > 64:
            raise ResourceGraphError("tag is invalid")
        value = ResourceTag(
            **self._tenant(),
            resource_id=resource.id,
            tag=normalized,
            created_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add_feature(value)
        await self._changed(resource, "resource.tag_added")
        return value

    async def add_note(
        self,
        *,
        note_id: uuid.UUID,
        resource_id: uuid.UUID,
        kind: NoteKind,
        content: str,
        expected_version: int,
        model_reference: str | None = None,
    ) -> ResourceNote:
        resource = await self._mutable(resource_id, expected_version)
        text = content.strip()
        if not text or len(text) > 10_000:
            raise ResourceGraphError("note content is invalid")
        if kind is NoteKind.AI and not model_reference:
            raise ResourceGraphError("AI notes require model provenance")
        note = ResourceNote(
            **self._tenant(),
            id=note_id,
            resource_id=resource.id,
            note_kind=kind.value,
            content=text,
            model_reference=model_reference,
            created_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add_feature(note)
        await self._changed(resource, "resource.note_added")
        return note

    async def attach(
        self,
        *,
        attachment_id: uuid.UUID,
        resource_id: uuid.UUID,
        attachment_resource_id: uuid.UUID,
        expected_version: int,
    ) -> ResourceAttachment:
        resource = await self._mutable(resource_id, expected_version)
        attachment = await self._require_resource(attachment_resource_id)
        if attachment.resource_type != "document":
            raise ResourceGraphError("attachments must reference document resources")
        value = ResourceAttachment(
            **self._tenant(),
            id=attachment_id,
            resource_id=resource.id,
            attachment_resource_id=attachment.id,
            created_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add_feature(value)
        await self._changed(resource, "resource.attachment_added")
        return value

    async def assign_owner(
        self, *, resource_id: uuid.UUID, owner_user_id: uuid.UUID, expected_version: int
    ) -> ResourceOwnership:
        await self._require_authorized("manage_workspace")
        resource = await self._locked(resource_id, expected_version)
        if not await self._repository.has_active_membership(owner_user_id):
            raise ResourceGraphError("resource owner must be an active workspace member")
        value = ResourceOwnership(
            **self._tenant(),
            resource_id=resource.id,
            owner_user_id=owner_user_id,
            assigned_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add_feature(value)
        await self._changed(resource, "resource.owner_assigned")
        return value

    async def grant(
        self,
        *,
        grant_id: uuid.UUID,
        resource_id: uuid.UUID,
        grantee_user_id: uuid.UUID,
        permission_key: str,
        expected_version: int,
    ) -> ResourceGrant:
        await self._require_authorized("manage_workspace")
        resource = await self._locked(resource_id, expected_version)
        if not await self._repository.has_active_membership(grantee_user_id):
            raise ResourceGraphError("resource grantee must be an active workspace member")
        if permission_key not in {"read_content", "update_content", "delete_content"}:
            raise ResourceGraphError("resource grant permission is invalid")
        value = ResourceGrant(
            **self._tenant(),
            id=grant_id,
            resource_id=resource.id,
            grantee_user_id=grantee_user_id,
            permission_key=permission_key,
            status="active",
            granted_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add_feature(value)
        await self._changed(resource, "resource.grant_created")
        return value

    async def link_external_reference(
        self,
        *,
        link_id: uuid.UUID,
        resource_id: uuid.UUID,
        external_reference_id: uuid.UUID,
        expected_version: int,
    ) -> ResourceExternalLink:
        resource = await self._mutable(resource_id, expected_version)
        if await self._repository.external_link(external_reference_id) is not None:
            raise ResourceGraphError("external reference is already linked")
        value = ResourceExternalLink(
            **self._tenant(),
            id=link_id,
            resource_id=resource.id,
            external_reference_id=external_reference_id,
            linked_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add_feature(value)
        await self._changed(resource, "resource.external_reference_linked")
        return value

    async def delete(self, *, resource_id: uuid.UUID, expected_version: int) -> Resource:
        if not await self._is_authorized("delete_content", resource_id=resource_id):
            raise ResourceGraphAuthorizationError("resource deletion is denied")
        resource = await self._locked(resource_id, expected_version)
        if resource.status == "deleted":
            raise ResourceGraphError("resource is already deleted")
        await self._repository.delete_relationships_for(resource.id)
        resource.status = "deleted"
        await self._changed(resource, "resource.deleted")
        return resource

    async def _mutable(self, resource_id: uuid.UUID, expected_version: int) -> Resource:
        if not await self._is_authorized("update_content", resource_id=resource_id):
            raise ResourceGraphAuthorizationError("resource update is denied")
        return await self._locked(resource_id, expected_version)

    async def _locked(self, resource_id: uuid.UUID, expected_version: int) -> Resource:
        resource = await self._require_resource(resource_id, for_update=True)
        require_expected_version(current=resource.version, expected=expected_version)
        if resource.status != "active":
            raise ResourceGraphError("deleted resource cannot be changed")
        return resource

    async def _require_resource(
        self, resource_id: uuid.UUID, *, for_update: bool = False
    ) -> Resource:
        resource = await self._repository.resource(resource_id, for_update=for_update)
        if resource is None:
            raise ResourceGraphError("resource does not exist")
        return resource

    async def _is_authorized(
        self, permission_key: str, *, resource_id: uuid.UUID | None = None
    ) -> bool:
        if await self._authorizer.authorize(self._context, permission_key):
            return True
        if resource_id is None:
            return False
        grant = await self._repository.grant_for_actor(
            resource_id=resource_id,
            actor_id=self._context.actor.actor_id,
            permission_key=permission_key,
        )
        return grant is not None

    async def _require_authorized(self, permission_key: str) -> None:
        if not await self._is_authorized(permission_key):
            raise ResourceGraphAuthorizationError("Resource Graph operation is denied")

    async def _changed(self, resource: Resource, event_type: str) -> None:
        resource.version += 1
        resource.updated_at = datetime.now(UTC)
        await self._record(resource, event_type, now=resource.updated_at)

    async def _record(self, resource: Resource, event_type: str, *, now: datetime) -> None:
        await self._audit.write(
            AuditInput(
                action=event_type,
                target_type="resource",
                target_id=resource.id,
                outcome="success",
                details={"resource_type": resource.resource_type, "version": resource.version},
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=resource.workspace_id,
                id=uuid.uuid4(),
                event_type=event_type,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="resource",
                aggregate_id=resource.id,
                aggregate_sequence=resource.version,
                actor_id=self._context.actor.actor_id,
                correlation_id=self._context.request.correlation_id,
                classification="internal",
                payload={
                    "resource_id": str(resource.id),
                    "resource_type": resource.resource_type,
                    "version": resource.version,
                },
                recorded_at=now,
                partition_key=now.strftime("%Y-%m"),
            )
        )
        await self._session.flush()
