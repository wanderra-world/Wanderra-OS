"""Authorized transactional H3-08 workflow application service."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent
from app.workflows.contracts import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    InstanceStatus,
    WorkflowDefinition,
    WorkflowError,
    decide_next,
    require_approval,
)
from app.workflows.models import (
    WorkflowApproval,
    WorkflowApprovalDecision,
    WorkflowDefinitionRecord,
    WorkflowDefinitionVersion,
    WorkflowInstance,
    WorkflowReceipt,
)
from app.workflows.repository import WorkflowRepository


class WorkflowAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class WorkflowService:
    def __init__(
        self, session: AsyncSession, context: ExecutionContext, *, authorizer: WorkflowAuthorizer
    ) -> None:
        self.session, self.context, self.authorizer = session, context, authorizer
        self.repository = WorkflowRepository(session, context)
        self.audit = AuditWriterService(session, context)

    async def _allow(self, permission: str) -> None:
        if not await self.authorizer.authorize(self.context, permission):
            raise WorkflowError("workflow authorization denied")

    def _tenant(self) -> dict[str, uuid.UUID]:
        tenant = self.context.tenant
        return {
            "organization_id": tenant.organization_id,
            "workspace_id": tenant.workspace_id,
            "cell_id": tenant.cell_id,
        }

    async def register(
        self, definition: WorkflowDefinition, *, now: datetime
    ) -> WorkflowDefinitionVersion:
        await self._allow("workflow.definition.manage")
        record = await self.repository.definition(definition.definition_id)
        if record is None:
            await self.repository.add(
                WorkflowDefinitionRecord(
                    **self._tenant(),
                    id=definition.definition_id,
                    name=definition.name,
                    created_by_user_id=self.context.actor.actor_id,
                    created_at=now,
                )
            )
        payload = definition.model_dump(mode="json")
        schema_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        value = WorkflowDefinitionVersion(
            **self._tenant(),
            definition_id=definition.definition_id,
            version=definition.version,
            schema_json=schema_json,
            schema_digest=hashlib.sha256(schema_json.encode()).hexdigest(),
            classification=definition.classification,
            policy_version=definition.policy_version,
            activated_at=None,
            created_at=now,
        )
        await self.repository.add(value)
        await self._record(
            aggregate_id=definition.definition_id,
            event="workflow.definition.registered",
            sequence=definition.version,
            classification=definition.classification,
            status="draft",
            occurred=now,
        )
        return value

    async def start(
        self,
        *,
        instance_id: uuid.UUID,
        definition_id: uuid.UUID,
        definition_version: int,
        input_payload: dict[str, object],
        idempotency_key: str,
        now: datetime,
    ) -> WorkflowInstance:
        await self._allow("workflow.instance.start")
        version = await self.repository.definition_version(definition_id, definition_version)
        if version is None or version.activated_at is None:
            raise WorkflowError("active workflow definition version does not exist")
        definition = WorkflowDefinition.model_validate_json(version.schema_json)
        digest = hashlib.sha256(
            json.dumps(input_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        value = WorkflowInstance(
            **self._tenant(),
            id=instance_id,
            definition_id=definition_id,
            definition_version=definition_version,
            status=InstanceStatus.RUNNING.value,
            current_step_key=definition.steps[0].key,
            state_json=json.dumps(input_payload, sort_keys=True),
            input_digest=digest,
            idempotency_key=idempotency_key,
            version=1,
            started_by_user_id=self.context.actor.actor_id,
            created_at=now,
            updated_at=now,
        )
        await self.repository.add(value)
        await self._record(
            aggregate_id=value.id,
            event="workflow.instance.started",
            sequence=1,
            classification=version.classification,
            status=value.status,
            occurred=now,
        )
        return value

    async def activate(
        self, definition_id: uuid.UUID, version_number: int, *, now: datetime
    ) -> WorkflowDefinitionVersion:
        await self._allow("workflow.definition.manage")
        version = await self.repository.definition_version(definition_id, version_number)
        if version is None:
            raise WorkflowError("workflow definition version does not exist")
        if version.activated_at is not None:
            return version
        version.activated_at = now
        record = await self.repository.definition(definition_id)
        if record is None:
            raise WorkflowError("workflow definition does not exist")
        record.status = "active"
        await self._record(
            aggregate_id=definition_id,
            event="workflow.definition.activated",
            sequence=version_number,
            classification=version.classification,
            status="active",
            occurred=now,
        )
        return version

    async def request_approval(self, request: ApprovalRequest) -> WorkflowApproval:
        await self._allow("workflow.approval.request")
        if await self.repository.instance(request.instance_id) is None:
            raise WorkflowError("workflow instance does not exist")
        value = WorkflowApproval(
            **self._tenant(),
            id=request.request_id,
            instance_id=request.instance_id,
            step_key=request.step_key,
            action_digest=request.action_digest,
            risk=request.risk,
            required_approvals=request.required_approvals,
            policy_version=request.policy_version,
            requested_by_user_id=request.requested_by_user_id,
            expires_at=request.expires_at,
            revoked_at=request.revoked_at,
        )
        return await self.repository.add(value)  # type: ignore[return-value]

    async def decide_approval(
        self, approval: WorkflowApproval, decision: ApprovalDecision
    ) -> WorkflowApprovalDecision:
        await self._allow("workflow.approval.decide")
        if decision.approver_id == approval.requested_by_user_id:
            raise ApprovalError("approval requester cannot self-approve")
        if decision.request_id != approval.id or decision.action_digest != approval.action_digest:
            raise ApprovalError("approval action digest mismatch")
        value = WorkflowApprovalDecision(
            **self._tenant(),
            id=decision.decision_id,
            approval_id=approval.id,
            approver_id=decision.approver_id,
            approved=decision.approved,
            action_digest=decision.action_digest,
            decided_at=decision.decided_at,
        )
        return await self.repository.add(value)  # type: ignore[return-value]

    @staticmethod
    def validate_approval(
        request: ApprovalRequest,
        decisions: tuple[ApprovalDecision, ...],
        *,
        now: datetime,
        current_action_digest: str,
        authorized: bool,
    ) -> None:
        require_approval(
            request,
            decisions,
            now=now,
            action_digest_value=current_action_digest,
            authorized=authorized,
        )

    async def transition(
        self,
        instance_id: uuid.UUID,
        *,
        outcome: str,
        expected_version: int,
        transition_key: str,
        now: datetime,
    ) -> WorkflowInstance:
        await self._allow("workflow.instance.execute")
        instance = await self.repository.instance(instance_id, for_update=True)
        if instance is None:
            raise WorkflowError("workflow instance does not exist")
        if instance.version != expected_version:
            raise WorkflowError("workflow version precondition failed")
        version = await self.repository.definition_version(
            instance.definition_id, instance.definition_version
        )
        if version is None or instance.current_step_key is None:
            raise WorkflowError("workflow definition binding is invalid")
        result = decide_next(
            WorkflowDefinition.model_validate_json(version.schema_json),
            current_key=instance.current_step_key,
            outcome=outcome,
            current_status=InstanceStatus(instance.status),
        )
        instance.current_step_key, instance.status, instance.version, instance.updated_at = (
            result.next_key,
            result.status.value,
            instance.version + 1,
            now,
        )
        await self.repository.add(
            WorkflowReceipt(
                **self._tenant(),
                id=uuid.uuid4(),
                instance_id=instance.id,
                transition_key=transition_key,
                outcome=result.status.value,
                action_digest=instance.input_digest,
                result_digest=None,
                compensation=False,
                uncertain=result.status is InstanceStatus.UNCERTAIN,
                created_at=now,
            )
        )
        await self.session.flush()
        await self._record(
            aggregate_id=instance.id,
            event="workflow.instance.transitioned",
            sequence=instance.version,
            classification=version.classification,
            status=instance.status,
            occurred=now,
        )
        return instance

    async def _record(
        self,
        *,
        aggregate_id: uuid.UUID,
        event: str,
        sequence: int,
        classification: str,
        status: str,
        occurred: datetime,
    ) -> None:
        await self.audit.write(
            AuditInput(
                action=event,
                target_type="workflow",
                target_id=aggregate_id,
                outcome="success",
                classification=classification,
                details={"version": sequence, "status": status},
            )
        )
        self.session.add(
            OutboxEvent(
                workspace_id=self.context.tenant.workspace_id,
                id=uuid.uuid4(),
                event_type=event,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="workflow",
                aggregate_id=aggregate_id,
                aggregate_sequence=sequence,
                actor_id=self.context.actor.actor_id,
                correlation_id=self.context.request.correlation_id,
                classification=classification,
                payload={"workflow_id": str(aggregate_id), "version": sequence, "status": status},
                recorded_at=occurred,
                partition_key=occurred.strftime("%Y-%m"),
            )
        )
        await self.session.flush()
