"""Authorized append-only H3-11 observation and operator evidence service."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.platform_hardening.contracts import (
    EvaluationResult,
    OperatorCommand,
    RecoveryDrillResult,
    TelemetryRecord,
)
from app.platform_hardening.models import (
    PlatformEvaluationRun,
    PlatformOperatorAction,
    PlatformRecoveryDrill,
    PlatformTelemetryRecord,
)
from app.platform_hardening.repository import PlatformHardeningRepository


class HardeningAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class PlatformHardeningService:
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: HardeningAuthorizer,
    ) -> None:
        self.context = context
        self.authorizer = authorizer
        self.repository = PlatformHardeningRepository(session, context)
        self.audit = AuditWriterService(session, context)

    def _tenant(self) -> dict[str, uuid.UUID]:
        return {
            "organization_id": self.context.tenant.organization_id,
            "workspace_id": self.context.tenant.workspace_id,
            "cell_id": self.context.tenant.cell_id,
        }

    async def _allow(self, permission: str) -> None:
        if not await self.authorizer.authorize(self.context, permission):
            raise PermissionError("platform hardening authorization denied")

    async def record_telemetry(
        self, value: TelemetryRecord, *, record_key: str
    ) -> PlatformTelemetryRecord:
        await self._allow("platform.telemetry.record")
        payload = self._canonical(value.model_dump(mode="json"))
        return await self.repository.add(
            PlatformTelemetryRecord(
                **self._tenant(),
                id=uuid.uuid4(),
                record_key=record_key,
                schema_version=value.schema_version,
                signal_key=value.signal_key,
                correlation_id=value.correlation_id,
                classification=value.classification,
                value=value.value,
                unit=value.unit,
                labels_json=self._canonical(value.labels),
                evidence_digest=self._digest(payload),
                occurred_at=value.occurred_at,
            )
        )  # type: ignore[return-value]

    async def record_evaluation(
        self, value: EvaluationResult, *, run_key: str
    ) -> PlatformEvaluationRun:
        await self._allow("platform.evaluation.record")
        return await self.repository.add(
            PlatformEvaluationRun(
                **self._tenant(),
                id=value.run_id,
                run_key=run_key,
                dataset_key=value.dataset_key,
                dataset_version=value.dataset_version,
                commit_sha=value.commit_sha,
                result_digest=value.result_digest,
                passed=value.passed,
                critical_findings=value.critical_findings,
                high_findings=value.high_findings,
                measured_at=value.measured_at,
            )
        )  # type: ignore[return-value]

    async def record_recovery(
        self, value: RecoveryDrillResult, *, drill_key: str
    ) -> PlatformRecoveryDrill:
        await self._allow("platform.recovery.record")
        return await self.repository.add(
            PlatformRecoveryDrill(
                **self._tenant(),
                id=value.drill_id,
                drill_key=drill_key,
                drill_type=value.drill_type,
                artifact_digest=value.artifact_digest,
                restored_digest=value.restored_digest,
                rpo_seconds=value.rpo_seconds,
                rto_seconds=value.rto_seconds,
                passed=value.verified,
                performed_at=value.performed_at,
            )
        )  # type: ignore[return-value]

    async def record_operator_action(self, value: OperatorCommand) -> PlatformOperatorAction:
        await self._allow(f"platform.operator.{value.action.value}")
        payload = self._canonical(value.model_dump(mode="json"))
        record = PlatformOperatorAction(
            **self._tenant(),
            id=value.command_id,
            actor_id=self.context.actor.actor_id,
            action=value.action.value,
            scope_type=value.scope_type,
            scope_reference=value.scope_reference,
            expected_version=value.expected_version,
            reason=value.reason,
            idempotency_key=value.idempotency_key,
            evidence_digest=self._digest(payload),
            occurred_at=value.occurred_at,
        )
        await self.repository.add(record)
        await self.audit.write(
            AuditInput(
                action=f"platform.operator.{value.action.value}",
                target_type=value.scope_type,
                target_id=value.command_id,
                outcome="success",
                classification="internal",
                details={
                    "scope_reference": value.scope_reference,
                    "expected_version": value.expected_version,
                    "evidence_digest": record.evidence_digest,
                },
            )
        )
        return record

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
