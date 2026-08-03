"""Deterministic contracts for versioned workflows and bound approvals."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class WorkflowError(ValueError):
    pass


class ApprovalError(WorkflowError):
    pass


class StepKind(StrEnum):
    COMMAND = "command"
    QUERY = "query"
    TASK = "task"
    WAIT = "wait"
    APPROVAL = "approval"


class InstanceStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPENSATION_FAILED = "compensation_failed"
    UNCERTAIN = "uncertain"


TERMINAL = frozenset(
    {
        InstanceStatus.SUCCEEDED,
        InstanceStatus.FAILED,
        InstanceStatus.CANCELLED,
        InstanceStatus.COMPENSATION_FAILED,
        InstanceStatus.UNCERTAIN,
    }
)
REFERENCE = re.compile(r"^[a-z][a-z0-9_.-]*\.v[1-9][0-9]*$")


class WorkflowStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str
    kind: StepKind
    reference: str
    next_key: str | None = None
    failure_key: str | None = None
    compensation_reference: str | None = None
    timeout_seconds: int = 300

    @model_validator(mode="after")
    def validate_step(self) -> WorkflowStep:
        if not self.key or not REFERENCE.fullmatch(self.reference):
            raise ValueError("step must reference a versioned registered contract")
        if self.compensation_reference is not None and not REFERENCE.fullmatch(
            self.compensation_reference
        ):
            raise ValueError("compensation must reference a versioned registered command")
        if not 1 <= self.timeout_seconds <= 86_400:
            raise ValueError("step timeout is invalid")
        return self


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    definition_id: uuid.UUID
    version: int
    name: str
    steps: tuple[WorkflowStep, ...]
    input_schema_version: int
    classification: str
    policy_version: int

    @model_validator(mode="after")
    def validate_definition(self) -> WorkflowDefinition:
        if (
            self.version < 1
            or self.input_schema_version < 1
            or self.policy_version < 1
            or not self.name.strip()
        ):
            raise ValueError("workflow definition metadata is invalid")
        if self.classification not in {"public", "internal", "confidential", "restricted"}:
            raise ValueError("workflow classification is invalid")
        keys = [step.key for step in self.steps]
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("workflow step keys must be unique")
        known = set(keys)
        for step in self.steps:
            if step.next_key is not None and step.next_key not in known:
                raise ValueError("workflow next step is unknown")
            if step.failure_key is not None and step.failure_key not in known:
                raise ValueError("workflow failure step is unknown")
        return self

    def step(self, key: str) -> WorkflowStep:
        for step in self.steps:
            if step.key == key:
                return step
        raise WorkflowError("workflow step does not exist")


class WorkflowTransition(BaseModel):
    model_config = ConfigDict(frozen=True)
    next_key: str | None
    status: InstanceStatus


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    request_id: uuid.UUID
    instance_id: uuid.UUID
    requested_by_user_id: uuid.UUID
    step_key: str
    action_digest: str
    risk: str
    required_approvals: int
    expires_at: datetime
    policy_version: int
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def validate_request(self) -> ApprovalRequest:
        if len(self.action_digest) != 64 or self.risk not in {"low", "medium", "high", "critical"}:
            raise ApprovalError("approval request is invalid")
        if self.required_approvals < 1 or self.policy_version < 1 or self.expires_at.tzinfo is None:
            raise ApprovalError("approval request is invalid")
        return self


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    decision_id: uuid.UUID
    request_id: uuid.UUID
    approver_id: uuid.UUID
    approved: bool
    action_digest: str
    decided_at: datetime


def action_digest(reference: str, payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {"reference": reference, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def decide_next(
    definition: WorkflowDefinition,
    *,
    current_key: str,
    outcome: str,
    current_status: InstanceStatus = InstanceStatus.RUNNING,
) -> WorkflowTransition:
    if current_status in TERMINAL:
        raise WorkflowError("terminal workflow instance cannot resume")
    step = definition.step(current_key)
    if outcome == "failed":
        return WorkflowTransition(
            next_key=step.failure_key,
            status=InstanceStatus.RUNNING if step.failure_key else InstanceStatus.FAILED,
        )
    if outcome not in {"succeeded", "resume"}:
        raise WorkflowError("workflow outcome is invalid")
    if step.next_key is None:
        return WorkflowTransition(next_key=None, status=InstanceStatus.SUCCEEDED)
    next_step = definition.step(step.next_key)
    status = (
        InstanceStatus.WAITING_APPROVAL
        if next_step.kind is StepKind.APPROVAL
        else InstanceStatus.WAITING
        if next_step.kind is StepKind.WAIT
        else InstanceStatus.RUNNING
    )
    return WorkflowTransition(next_key=next_step.key, status=status)


def require_approval(
    request: ApprovalRequest,
    decisions: tuple[ApprovalDecision, ...],
    *,
    now: datetime,
    action_digest_value: str,
    authorized: bool,
) -> None:
    if not authorized:
        raise ApprovalError("authorization revalidation failed")
    if request.revoked_at is not None:
        raise ApprovalError("approval was revoked")
    if now >= request.expires_at:
        raise ApprovalError("approval expired")
    if action_digest_value != request.action_digest:
        raise ApprovalError("approval action digest mismatch")
    valid = {
        decision.approver_id
        for decision in decisions
        if decision.request_id == request.request_id
        and decision.approver_id != request.requested_by_user_id
        and decision.approved
        and decision.action_digest == request.action_digest
    }
    if len(valid) < request.required_approvals:
        raise ApprovalError("approval quorum not satisfied")
