"""Typed, inert, deterministic contracts for the H3-10 agent platform."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator


class AgentPlatformError(ValueError):
    pass


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


RISK_RANK = {value: index for index, value in enumerate(RiskLevel)}
CLASSIFICATION_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}
KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
APPLICATION_REFERENCE = re.compile(r"^[a-z][a-z0-9_.-]*\.v[1-9][0-9]*$")
SENSITIVE_KEYS = ("password", "secret", "token", "credential", "raw_payload")


class PlanStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    ACCEPTED = "accepted"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"


class ExecutionOutcome(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"


class Budget(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_tokens: int
    max_cost_micros: int
    max_tool_calls: int
    max_seconds: int

    @model_validator(mode="after")
    def positive_limits(self) -> Budget:
        if (
            min(
                self.max_tokens,
                self.max_cost_micros,
                self.max_tool_calls,
                self.max_seconds,
            )
            < 0
        ):
            raise AgentPlatformError("budget limits cannot be negative")
        return self


class AgentManifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    manifest_id: uuid.UUID
    version: int
    name: str
    purpose: str
    owner_user_id: uuid.UUID
    allowed_tool_classes: tuple[str, ...]
    risk_ceiling: RiskLevel
    budget: Budget
    model_policy_key: str
    evaluation_set_key: str
    input_schema_version: int
    output_schema_version: int
    enabled: bool

    @model_validator(mode="after")
    def validate_manifest(self) -> AgentManifest:
        if self.version < 1 or self.input_schema_version < 1 or self.output_schema_version < 1:
            raise AgentPlatformError("manifest version is invalid")
        if not self.name.strip() or not self.purpose.strip():
            raise AgentPlatformError("manifest name and purpose are required")
        if not self.allowed_tool_classes or any(
            not KEY.fullmatch(value) for value in self.allowed_tool_classes
        ):
            raise AgentPlatformError("manifest tool classes are invalid")
        if not KEY.fullmatch(self.model_policy_key) or not KEY.fullmatch(self.evaluation_set_key):
            raise AgentPlatformError("manifest policy identity is invalid")
        return self


class ToolManifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    tool_id: uuid.UUID
    key: str
    version: int
    command_reference: str
    permission_key: str
    risk: RiskLevel
    input_schema_version: int
    output_schema_version: int
    enabled: bool

    @model_validator(mode="after")
    def validate_tool(self) -> ToolManifest:
        if not KEY.fullmatch(self.key) or self.version < 1:
            raise AgentPlatformError("tool identity is invalid")
        if not APPLICATION_REFERENCE.fullmatch(self.command_reference):
            raise AgentPlatformError("tool must reference an application command or query")
        if not KEY.fullmatch(self.permission_key):
            raise AgentPlatformError("tool permission identity is invalid")
        if self.input_schema_version < 1 or self.output_schema_version < 1:
            raise AgentPlatformError("tool schema version is invalid")
        return self


class Delegation(BaseModel):
    model_config = ConfigDict(frozen=True)
    delegation_id: uuid.UUID
    actor_id: uuid.UUID
    permissions: tuple[str, ...]
    risk_ceiling: RiskLevel
    expires_at: datetime
    parent_delegation_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_delegation(self) -> Delegation:
        if self.expires_at.tzinfo is None:
            raise AgentPlatformError("delegation expiry must be timezone-aware")
        if not self.permissions or any(not KEY.fullmatch(value) for value in self.permissions):
            raise AgentPlatformError("delegation permissions are invalid")
        return self


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str
    tool_key: str
    tool_version: int
    input_payload: dict[str, object]
    expected_resource_version: int
    expected_outcome: str
    verification_reference: str
    risk: RiskLevel
    approval_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_step(self) -> PlanStep:
        if not KEY.fullmatch(self.key) or not KEY.fullmatch(self.tool_key):
            raise AgentPlatformError("plan step identity is invalid")
        if self.tool_version < 1 or self.expected_resource_version < 0:
            raise AgentPlatformError("plan step version is invalid")
        if not APPLICATION_REFERENCE.fullmatch(self.verification_reference):
            raise AgentPlatformError("plan verification reference is invalid")
        if not self.expected_outcome.strip():
            raise AgentPlatformError("plan expected outcome is required")
        if any(marker in key.casefold() for key in self.input_payload for marker in SENSITIVE_KEYS):
            raise AgentPlatformError("sensitive plan input is prohibited")
        serialized = json.dumps(self.input_payload, sort_keys=True, separators=(",", ":"))
        if len(serialized.encode()) > 32_768:
            raise AgentPlatformError("plan step input exceeds the size limit")
        return self


class PlanProposal(BaseModel):
    model_config = ConfigDict(frozen=True)
    plan_id: uuid.UUID
    version: int
    manifest_id: uuid.UUID
    manifest_version: int
    model_policy_key: str
    classification: str
    evidence_references: tuple[str, ...]
    assumptions: tuple[str, ...]
    estimated_tokens: int
    estimated_cost_micros: int
    steps: tuple[PlanStep, ...]
    status: PlanStatus = PlanStatus.PROPOSED

    @model_validator(mode="after")
    def validate_proposal(self) -> PlanProposal:
        if self.version < 1 or self.manifest_version < 1:
            raise AgentPlatformError("plan version is invalid")
        if self.classification not in CLASSIFICATION_RANK:
            raise AgentPlatformError("plan classification is invalid")
        if not KEY.fullmatch(self.model_policy_key):
            raise AgentPlatformError("plan model policy is invalid")
        if not self.evidence_references or not self.steps:
            raise AgentPlatformError("plan evidence and steps are required")
        if self.estimated_tokens < 0 or self.estimated_cost_micros < 0:
            raise AgentPlatformError("plan estimate is invalid")
        keys = [step.key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise AgentPlatformError("plan step keys must be unique")
        return self


class ToolExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    orchestration_id: uuid.UUID
    plan_id: uuid.UUID
    plan_version: int
    step_key: str
    command_reference: str
    permission_key: str
    input_payload: dict[str, object]
    expected_resource_version: int
    action_digest: str
    idempotency_key: str
    correlation_id: str
    approval_id: uuid.UUID | None = None


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    result_payload: dict[str, object]
    command_receipt_id: uuid.UUID
    verification_passed: bool | None


class ApplicationToolExecutor(Protocol):
    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...


class PlannerPort(Protocol):
    async def propose(self, context_digest: str, schema_version: int) -> dict[str, object]: ...


def attenuate_delegation(
    parent: Delegation,
    *,
    delegation_id: uuid.UUID,
    permissions: tuple[str, ...],
    risk_ceiling: RiskLevel,
    expires_at: datetime,
) -> Delegation:
    if not set(permissions).issubset(parent.permissions):
        raise AgentPlatformError("delegation cannot amplify permissions")
    if RISK_RANK[risk_ceiling] > RISK_RANK[parent.risk_ceiling]:
        raise AgentPlatformError("delegation cannot amplify risk")
    if expires_at > parent.expires_at:
        raise AgentPlatformError("delegation cannot extend expiry")
    return Delegation(
        delegation_id=delegation_id,
        actor_id=parent.actor_id,
        permissions=permissions,
        risk_ceiling=risk_ceiling,
        expires_at=expires_at,
        parent_delegation_id=parent.delegation_id,
    )


def reserve_budget(
    available: Budget,
    *,
    tokens: int,
    cost_micros: int,
    tool_calls: int,
    seconds: int,
) -> Budget:
    requested = (tokens, cost_micros, tool_calls, seconds)
    current = (
        available.max_tokens,
        available.max_cost_micros,
        available.max_tool_calls,
        available.max_seconds,
    )
    if min(requested) < 0 or any(value > limit for value, limit in zip(requested, current)):
        raise AgentPlatformError("agent budget exhausted")
    return Budget(
        max_tokens=current[0] - tokens,
        max_cost_micros=current[1] - cost_micros,
        max_tool_calls=current[2] - tool_calls,
        max_seconds=current[3] - seconds,
    )


def action_digest(command_reference: str, payload: dict[str, object], version: int) -> str:
    normalized = json.dumps(
        {"command": command_reference, "payload": payload, "resource_version": version},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def validate_plan(
    proposal: PlanProposal,
    manifest: AgentManifest,
    tools: dict[str, ToolManifest],
) -> PlanProposal:
    if proposal.status is not PlanStatus.PROPOSED:
        raise AgentPlatformError("only a proposed plan can be validated")
    if (proposal.manifest_id, proposal.manifest_version) != (
        manifest.manifest_id,
        manifest.version,
    ) or not manifest.enabled:
        raise AgentPlatformError("plan manifest binding is invalid")
    if proposal.model_policy_key != manifest.model_policy_key:
        raise AgentPlatformError("plan model policy changed")
    if (
        proposal.estimated_tokens > manifest.budget.max_tokens
        or proposal.estimated_cost_micros > manifest.budget.max_cost_micros
        or len(proposal.steps) > manifest.budget.max_tool_calls
    ):
        raise AgentPlatformError("plan exceeds manifest budget")
    for step in proposal.steps:
        registered = tools.get(step.tool_key)
        if registered is None or registered.version != step.tool_version or not registered.enabled:
            raise AgentPlatformError("plan references an unregistered or disabled tool")
        tool_class = step.tool_key.split(".", 1)[0]
        if tool_class not in manifest.allowed_tool_classes:
            raise AgentPlatformError("tool class is outside the manifest")
        if step.risk != registered.risk or RISK_RANK[step.risk] > RISK_RANK[manifest.risk_ceiling]:
            raise AgentPlatformError("plan risk exceeds the manifest")
    return proposal.model_copy(update={"status": PlanStatus.VALIDATED})


def validate_execution(
    step: PlanStep,
    tool: ToolManifest,
    manifest: AgentManifest,
    delegation: Delegation,
    *,
    now: datetime,
    authorized: bool,
    approval_valid: bool,
) -> str:
    if now.tzinfo is None:
        raise AgentPlatformError("execution clock must be timezone-aware")
    if not manifest.enabled or not tool.enabled:
        raise AgentPlatformError("manifest or tool is disabled")
    if delegation.expires_at <= now:
        raise AgentPlatformError("delegation is expired")
    if (step.tool_key, step.tool_version) != (tool.key, tool.version):
        raise AgentPlatformError("tool binding changed")
    if tool.permission_key not in delegation.permissions or not authorized:
        raise AgentPlatformError("execution authorization denied")
    if (
        RISK_RANK[step.risk] > RISK_RANK[manifest.risk_ceiling]
        or RISK_RANK[step.risk] > RISK_RANK[delegation.risk_ceiling]
    ):
        raise AgentPlatformError("execution risk exceeds the active ceiling")
    if step.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL} and (
        step.approval_id is None or not approval_valid
    ):
        raise AgentPlatformError("valid digest-bound approval is required")
    return action_digest(
        tool.command_reference,
        step.input_payload,
        step.expected_resource_version,
    )


def verify_result(_: object, *, verification_passed: bool | None) -> ExecutionOutcome:
    if verification_passed is True:
        return ExecutionOutcome.VERIFIED
    if verification_passed is False:
        return ExecutionOutcome.FAILED
    return ExecutionOutcome.UNCERTAIN
