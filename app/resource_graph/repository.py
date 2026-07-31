"""Execution-context-bound persistence for H3-01 resources."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.memberships.models import WorkspaceMembership
from app.resource_graph.models import (
    Resource,
    ResourceExternalLink,
    ResourceGrant,
    ResourceProjection,
    ResourceRelationship,
)


class ResourceGraphRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add_resource_pair(
        self,
        projection: ResourceProjection,
        resource: Resource,
    ) -> Resource:
        self.require_workspace(resource.workspace_id)
        self.require_workspace(projection.workspace_id)
        if (
            projection.resource_id != resource.id
            or projection.id != resource.projection_id
            or projection.resource_type != resource.resource_type
        ):
            raise ValueError("resource and typed projection binding do not match")
        self.session.add_all((projection, resource))
        await self.session.flush()
        return resource

    async def add_feature(self, value: object) -> object:
        if isinstance(value, (Resource, ResourceProjection)):
            raise ValueError("direct resource registry insertion is prohibited")
        workspace_id = getattr(value, "workspace_id")
        self.require_workspace(workspace_id)
        self.session.add(value)
        await self.session.flush()
        return value

    async def resource(
        self, resource_id: uuid.UUID, *, for_update: bool = False
    ) -> Resource | None:
        statement = select(Resource).where(
            Resource.workspace_id == self.context.tenant.workspace_id,
            Resource.id == resource_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def projection_for_resource(self, resource_id: uuid.UUID) -> ResourceProjection | None:
        return await self.session.scalar(
            select(ResourceProjection).where(
                ResourceProjection.workspace_id == self.context.tenant.workspace_id,
                ResourceProjection.resource_id == resource_id,
            )
        )

    async def active_relationship_count(
        self, *, relationship_type: str, source_resource_id: uuid.UUID
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(ResourceRelationship)
                .where(
                    ResourceRelationship.workspace_id == self.context.tenant.workspace_id,
                    ResourceRelationship.relationship_type == relationship_type,
                    ResourceRelationship.source_resource_id == source_resource_id,
                    ResourceRelationship.status == "active",
                )
            )
            or 0
        )

    async def grant_for_actor(
        self,
        *,
        resource_id: uuid.UUID,
        actor_id: uuid.UUID,
        permission_key: str,
    ) -> ResourceGrant | None:
        return await self.session.scalar(
            select(ResourceGrant).where(
                ResourceGrant.workspace_id == self.context.tenant.workspace_id,
                ResourceGrant.resource_id == resource_id,
                ResourceGrant.grantee_user_id == actor_id,
                ResourceGrant.permission_key == permission_key,
                ResourceGrant.status == "active",
            )
        )

    async def has_active_membership(self, user_id: uuid.UUID) -> bool:
        return (
            await self.session.scalar(
                select(WorkspaceMembership.id).where(
                    WorkspaceMembership.workspace_id == self.context.tenant.workspace_id,
                    WorkspaceMembership.user_id == user_id,
                    WorkspaceMembership.status == "active",
                )
            )
            is not None
        )

    async def external_link(self, external_reference_id: uuid.UUID) -> ResourceExternalLink | None:
        return await self.session.scalar(
            select(ResourceExternalLink).where(
                ResourceExternalLink.workspace_id == self.context.tenant.workspace_id,
                ResourceExternalLink.external_reference_id == external_reference_id,
            )
        )

    async def delete_relationships_for(self, resource_id: uuid.UUID) -> None:
        await self.session.execute(
            update(ResourceRelationship)
            .where(
                ResourceRelationship.workspace_id == self.context.tenant.workspace_id,
                ResourceRelationship.status == "active",
                or_(
                    ResourceRelationship.source_resource_id == resource_id,
                    ResourceRelationship.target_resource_id == resource_id,
                ),
            )
            .values(status="deleted", version=ResourceRelationship.version + 1)
        )
