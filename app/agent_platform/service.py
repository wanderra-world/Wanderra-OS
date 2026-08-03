"""Authorized transactional H3-10 registration, planning, and orchestration service."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_platform.contracts import (
    AgentManifest,
    AgentPlatformError,
    ApplicationToolExecutor,
    Budget,
    Delegation,
    ExecutionOutcome,
    PlannerPort,
    PlanProposal,
    PlanStatus,
    RiskLevel,
    ToolExecutionRequest,
    ToolManifest,
    action_digest,
    reserve_budget,
    validate_execution,
    validate_plan,
    verify_result,
)
from app.agent_platform.models import (
    AgentBudgetReservation,
    AgentDelegation,
    AgentEvaluationRun,
    AgentExecutionReceipt,
    AgentManifestRecord,
    AgentManifestVersion,
    AgentOrchestration,
    AgentPlan,
    AgentPlanStep,
    AgentToolRecord,
    AgentToolVersion,
)
from app.agent_platform.repository import AgentPlatformRepository
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent


class AgentPlatformAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class ApprovalValidator(Protocol):
    async def validate(
        self,
        context: ExecutionContext,
        approval_id: uuid.UUID,
        action_digest: str,
        now: datetime,
    ) -> bool: ...


class AgentPlatformService:
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: AgentPlatformAuthorizer,
    ) -> None:
        self.session = session
        self.context = context
        self.authorizer = authorizer
        self.repository = AgentPlatformRepository(session, context)
        self.audit = AuditWriterService(session, context)

    def _tenant(self) -> dict[str, uuid.UUID]:
        tenant = self.context.tenant
        return {
            "organization_id": tenant.organization_id,
            "workspace_id": tenant.workspace_id,
            "cell_id": tenant.cell_id,
        }

    async def _allow(self, permission: str) -> None:
        if not await self.authorizer.authorize(self.context, permission):
            raise AgentPlatformError("agent platform authorization denied")

    async def register_manifest(
        self,
        manifest: AgentManifest,
        *,
        classification: str,
        policy_version: int,
        now: datetime,
    ) -> AgentManifestVersion:
        await self._allow("agent.manifest.manage")
        if manifest.owner_user_id != self.context.actor.actor_id:
            raise AgentPlatformError("manifest owner must approve registration")
        record = await self.repository.manifest(manifest.manifest_id)
        if record is None:
            record = AgentManifestRecord(
                **self._tenant(),
                id=manifest.manifest_id,
                name=manifest.name,
                owner_user_id=manifest.owner_user_id,
                enabled=False,
                created_at=now,
            )
            await self.repository.add(record)
        payload = self._canonical(manifest.model_dump(mode="json"))
        value = AgentManifestVersion(
            **self._tenant(),
            manifest_id=manifest.manifest_id,
            version=manifest.version,
            manifest_json=payload,
            manifest_digest=self._digest(payload),
            classification=classification,
            policy_version=policy_version,
            activated_at=None,
            created_at=now,
        )
        await self.repository.add(value)
        await self._record(
            event="agent.manifest.registered",
            aggregate_id=manifest.manifest_id,
            sequence=manifest.version,
            classification=classification,
            status="registered",
            occurred=now,
        )
        return value

    async def activate_manifest(
        self, manifest_id: uuid.UUID, version: int, *, now: datetime
    ) -> AgentManifestVersion:
        await self._allow("agent.manifest.manage")
        record = await self.repository.manifest(manifest_id)
        value = await self.repository.manifest_version(manifest_id, version)
        if record is None or value is None:
            raise AgentPlatformError("agent manifest version does not exist")
        if not await self.repository.has_passing_evaluation(manifest_id, version):
            raise AgentPlatformError("passing synthetic evaluation is required")
        value.activated_at = now
        record.enabled = True
        return value

    async def disable_manifest(self, manifest_id: uuid.UUID, *, now: datetime) -> None:
        """Fail closed for new execution while retaining immutable versions."""
        await self._allow("agent.manifest.manage")
        record = await self.repository.manifest(manifest_id)
        if record is None:
            raise AgentPlatformError("agent manifest does not exist")
        record.enabled = False
        await self._record(
            event="agent.manifest.disabled",
            aggregate_id=manifest_id,
            sequence=1,
            classification="internal",
            status="disabled",
            occurred=now,
        )

    async def register_tool(self, tool: ToolManifest, *, now: datetime) -> AgentToolVersion:
        await self._allow("agent.tool.manage")
        record = await self.repository.tool(tool.key)
        if record is None:
            record = AgentToolRecord(
                **self._tenant(),
                id=tool.tool_id,
                tool_key=tool.key,
                owner_user_id=self.context.actor.actor_id,
                enabled=False,
                created_at=now,
            )
            await self.repository.add(record)
        elif record.id != tool.tool_id:
            raise AgentPlatformError("tool key is already registered")
        payload = self._canonical(tool.model_dump(mode="json"))
        value = AgentToolVersion(
            **self._tenant(),
            tool_id=tool.tool_id,
            version=tool.version,
            tool_json=payload,
            tool_digest=self._digest(payload),
            risk=tool.risk.value,
            activated_at=None,
            created_at=now,
        )
        await self.repository.add(value)
        await self._record(
            event="agent.tool.registered",
            aggregate_id=tool.tool_id,
            sequence=tool.version,
            classification="internal",
            status="registered",
            occurred=now,
        )
        return value

    async def activate_tool(self, key: str, version: int, *, now: datetime) -> AgentToolVersion:
        await self._allow("agent.tool.manage")
        record = await self.repository.tool(key)
        if record is None:
            raise AgentPlatformError("registered tool does not exist")
        value = await self.repository.tool_version(record.id, version)
        if value is None:
            raise AgentPlatformError("registered tool version does not exist")
        value.activated_at = now
        record.enabled = True
        return value

    async def disable_tool(self, key: str, *, now: datetime) -> None:
        """Emergency-disable a tool without destroying registry evidence."""
        await self._allow("agent.tool.manage")
        record = await self.repository.tool(key)
        if record is None:
            raise AgentPlatformError("registered tool does not exist")
        record.enabled = False
        await self._record(
            event="agent.tool.disabled",
            aggregate_id=record.id,
            sequence=1,
            classification="internal",
            status="disabled",
            occurred=now,
        )

    async def record_delegation(
        self,
        delegation: Delegation,
        *,
        now: datetime,
    ) -> AgentDelegation:
        await self._allow("agent.delegation.create")
        if delegation.actor_id != self.context.actor.actor_id:
            raise AgentPlatformError("delegation actor binding is invalid")
        payload = self._canonical(delegation.model_dump(mode="json"))
        value = AgentDelegation(
            **self._tenant(),
            id=delegation.delegation_id,
            actor_id=delegation.actor_id,
            parent_delegation_id=delegation.parent_delegation_id,
            permissions_json=self._canonical(list(delegation.permissions)),
            risk_ceiling=delegation.risk_ceiling.value,
            expires_at=delegation.expires_at,
            revoked_at=None,
            delegation_digest=self._digest(payload),
        )
        await self.repository.add(value)
        await self._record(
            event="agent.delegation.recorded",
            aggregate_id=delegation.delegation_id,
            sequence=1,
            classification="internal",
            status="active",
            occurred=now,
        )
        return value

    async def record_evaluation(
        self,
        manifest: AgentManifest,
        *,
        run_key: str,
        result: dict[str, object],
        passed: bool,
        now: datetime,
    ) -> AgentEvaluationRun:
        """Persist synthetic conformance evidence required before activation."""
        await self._allow("agent.evaluation.record")
        if not run_key.startswith("synthetic."):
            raise AgentPlatformError("only synthetic conformance evaluations are allowed")
        payload = self._canonical(result)
        value = AgentEvaluationRun(
            **self._tenant(),
            id=uuid.uuid4(),
            run_key=run_key,
            manifest_id=manifest.manifest_id,
            manifest_version=manifest.version,
            evaluation_set_key=manifest.evaluation_set_key,
            result_digest=self._digest(payload),
            passed=passed,
            created_at=now,
        )
        return await self.repository.add(value)  # type: ignore[return-value]

    async def propose(
        self,
        planner: PlannerPort,
        *,
        context_digest: str,
        manifest: AgentManifest,
        idempotency_key: str,
        classification: str,
        policy_version: int,
        now: datetime,
    ) -> PlanProposal:
        await self._allow("agent.plan.propose")
        if not manifest.enabled:
            raise AgentPlatformError("agent manifest is disabled")
        raw = await planner.propose(context_digest, manifest.input_schema_version)
        proposal = PlanProposal.model_validate(raw)
        if (proposal.manifest_id, proposal.manifest_version) != (
            manifest.manifest_id,
            manifest.version,
        ):
            raise AgentPlatformError("planner changed the manifest binding")
        payload = self._canonical(proposal.model_dump(mode="json"))
        await self.repository.add(
            AgentPlan(
                **self._tenant(),
                id=proposal.plan_id,
                version=proposal.version,
                manifest_id=proposal.manifest_id,
                manifest_version=proposal.manifest_version,
                plan_json=payload,
                plan_digest=self._digest(payload),
                status=PlanStatus.PROPOSED.value,
                classification=classification,
                policy_version=policy_version,
                idempotency_key=idempotency_key,
                created_by_user_id=self.context.actor.actor_id,
                created_at=now,
            )
        )
        return proposal

    async def accept_plan(
        self,
        proposal: PlanProposal,
        manifest: AgentManifest,
        tools: dict[str, ToolManifest],
        *,
        now: datetime,
    ) -> PlanProposal:
        await self._allow("agent.plan.accept")
        validated = validate_plan(proposal, manifest, tools)
        record = await self.repository.plan(proposal.plan_id, proposal.version, for_update=True)
        if record is None or record.plan_digest != self._digest(
            self._canonical(proposal.model_dump(mode="json"))
        ):
            raise AgentPlatformError("persisted plan digest mismatch")
        record.status = PlanStatus.ACCEPTED.value
        for step in validated.steps:
            tool = tools[step.tool_key]
            await self.repository.add(
                AgentPlanStep(
                    **self._tenant(),
                    plan_id=validated.plan_id,
                    plan_version=validated.version,
                    step_key=step.key,
                    tool_id=tool.tool_id,
                    tool_key=step.tool_key,
                    tool_version=step.tool_version,
                    step_json=self._canonical(step.model_dump(mode="json")),
                    action_digest=action_digest(
                        tool.command_reference,
                        step.input_payload,
                        step.expected_resource_version,
                    ),
                    status="accepted",
                )
            )
        return validated.model_copy(update={"status": PlanStatus.ACCEPTED})

    async def start_orchestration(
        self,
        proposal: PlanProposal,
        delegation: Delegation,
        *,
        orchestration_id: uuid.UUID,
        idempotency_key: str,
        now: datetime,
    ) -> AgentOrchestration:
        await self._allow("agent.orchestration.start")
        if proposal.status is not PlanStatus.ACCEPTED or delegation.expires_at <= now:
            raise AgentPlatformError("accepted plan and active delegation are required")
        value = AgentOrchestration(
            **self._tenant(),
            id=orchestration_id,
            plan_id=proposal.plan_id,
            plan_version=proposal.version,
            delegation_id=delegation.delegation_id,
            status=PlanStatus.EXECUTING.value,
            current_step_key=proposal.steps[0].key,
            idempotency_key=idempotency_key,
            version=1,
            cancelled_at=None,
            created_at=now,
        )
        return await self.repository.add(value)  # type: ignore[return-value]

    async def execute_step(
        self,
        *,
        orchestration_id: uuid.UUID,
        proposal: PlanProposal,
        manifest: AgentManifest,
        tool: ToolManifest,
        delegation: Delegation,
        executor: ApplicationToolExecutor,
        approval_validator: ApprovalValidator,
        budget: Budget,
        idempotency_key: str,
        now: datetime,
    ) -> AgentExecutionReceipt:
        orchestration = await self.repository.orchestration(orchestration_id, for_update=True)
        if orchestration is None or orchestration.cancelled_at is not None:
            raise AgentPlatformError("orchestration is unavailable")
        step = proposal.steps[
            [value.key for value in proposal.steps].index(orchestration.current_step_key)
        ]
        authorized = await self.authorizer.authorize(self.context, tool.permission_key)
        approval_valid = step.risk not in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        if step.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            provisional_digest = action_digest(
                tool.command_reference,
                step.input_payload,
                step.expected_resource_version,
            )
            approval_valid = step.approval_id is not None and await approval_validator.validate(
                self.context,
                step.approval_id,
                provisional_digest,
                now,
            )
        digest = validate_execution(
            step,
            tool,
            manifest,
            delegation,
            now=now,
            authorized=authorized,
            approval_valid=approval_valid,
        )
        reserve_budget(
            budget,
            tokens=proposal.estimated_tokens,
            cost_micros=proposal.estimated_cost_micros,
            tool_calls=1,
            seconds=1,
        )
        await self.repository.add(
            AgentBudgetReservation(
                **self._tenant(),
                id=uuid.uuid4(),
                manifest_id=manifest.manifest_id,
                manifest_version=manifest.version,
                plan_id=proposal.plan_id,
                plan_version=proposal.version,
                tokens=proposal.estimated_tokens,
                cost_micros=proposal.estimated_cost_micros,
                tool_calls=1,
                seconds=1,
                idempotency_key=idempotency_key,
                released_at=None,
                created_at=now,
            )
        )
        result = await executor.execute(
            ToolExecutionRequest(
                orchestration_id=orchestration_id,
                plan_id=proposal.plan_id,
                plan_version=proposal.version,
                step_key=step.key,
                command_reference=tool.command_reference,
                permission_key=tool.permission_key,
                input_payload=step.input_payload,
                expected_resource_version=step.expected_resource_version,
                action_digest=digest,
                idempotency_key=idempotency_key,
                correlation_id=self.context.request.correlation_id,
                approval_id=step.approval_id,
            )
        )
        outcome = verify_result(
            result.result_payload, verification_passed=result.verification_passed
        )
        result_payload = self._canonical(result.result_payload)
        receipt = AgentExecutionReceipt(
            **self._tenant(),
            id=uuid.uuid4(),
            orchestration_id=orchestration_id,
            step_key=step.key,
            command_receipt_id=result.command_receipt_id,
            action_digest=digest,
            result_digest=self._digest(result_payload),
            outcome=outcome.value,
            verified=outcome is ExecutionOutcome.VERIFIED,
            created_at=now,
        )
        await self.repository.add(receipt)
        current_index = [value.key for value in proposal.steps].index(step.key)
        if outcome is ExecutionOutcome.VERIFIED and current_index + 1 < len(proposal.steps):
            orchestration.status = PlanStatus.EXECUTING.value
            orchestration.current_step_key = proposal.steps[current_index + 1].key
        else:
            orchestration.status = (
                PlanStatus.SUCCEEDED.value
                if outcome is ExecutionOutcome.VERIFIED
                else PlanStatus.UNCERTAIN.value
                if outcome is ExecutionOutcome.UNCERTAIN
                else PlanStatus.FAILED.value
            )
            orchestration.current_step_key = None
        orchestration.version += 1
        await self._record(
            event="agent.execution.receipted",
            aggregate_id=orchestration_id,
            sequence=orchestration.version,
            classification=proposal.classification,
            status=orchestration.status,
            occurred=now,
        )
        return receipt

    async def cancel(self, orchestration_id: uuid.UUID, *, now: datetime) -> None:
        await self._allow("agent.orchestration.cancel")
        value = await self.repository.orchestration(orchestration_id, for_update=True)
        if value is None:
            raise AgentPlatformError("orchestration does not exist")
        if value.status in {PlanStatus.SUCCEEDED.value, PlanStatus.FAILED.value}:
            raise AgentPlatformError("terminal orchestration cannot be cancelled")
        value.status = PlanStatus.CANCELLED.value
        value.cancelled_at = now
        value.current_step_key = None
        value.version += 1

    async def _record(
        self,
        *,
        event: str,
        aggregate_id: uuid.UUID,
        sequence: int,
        classification: str,
        status: str,
        occurred: datetime,
    ) -> None:
        await self.audit.write(
            AuditInput(
                action=event,
                target_type="agent_platform",
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
                aggregate_type="agent_platform",
                aggregate_id=aggregate_id,
                aggregate_sequence=sequence,
                actor_id=self.context.actor.actor_id,
                correlation_id=self.context.request.correlation_id,
                classification=classification,
                payload={"aggregate_id": str(aggregate_id), "status": status},
                recorded_at=occurred,
                partition_key=occurred.strftime("%Y-%m"),
            )
        )
        await self.session.flush()

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
