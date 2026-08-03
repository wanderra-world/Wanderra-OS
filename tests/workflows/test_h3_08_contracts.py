from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.workflows.contracts import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    InstanceStatus,
    StepKind,
    WorkflowDefinition,
    WorkflowError,
    WorkflowStep,
    action_digest,
    decide_next,
    require_approval,
)


def definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id=uuid4(),
        version=1,
        name="review",
        steps=(
            WorkflowStep(
                key="prepare", kind=StepKind.COMMAND, reference="task.read.v1", next_key="approve"
            ),
            WorkflowStep(
                key="approve",
                kind=StepKind.APPROVAL,
                reference="approval.human.v1",
                next_key="finish",
            ),
            WorkflowStep(key="finish", kind=StepKind.COMMAND, reference="task.complete.v1"),
        ),
        input_schema_version=1,
        classification="internal",
        policy_version=1,
    )


def test_definition_is_typed_immutable_and_compatible() -> None:
    value = definition()
    assert value.step("prepare").next_key == "approve"
    with pytest.raises(Exception):
        value.version = 2
    with pytest.raises(ValueError, match="registered"):
        WorkflowStep(key="bad", kind=StepKind.COMMAND, reference="python:call")


def test_deterministic_transition_and_terminal_resume_denial() -> None:
    transition = decide_next(definition(), current_key="prepare", outcome="succeeded")
    assert transition.next_key == "approve"
    assert transition.status is InstanceStatus.WAITING_APPROVAL
    assert (
        decide_next(definition(), current_key="finish", outcome="succeeded").status
        is InstanceStatus.SUCCEEDED
    )
    with pytest.raises(WorkflowError, match="terminal"):
        decide_next(
            definition(),
            current_key="finish",
            outcome="resume",
            current_status=InstanceStatus.CANCELLED,
        )


def test_approval_is_bound_to_digest_and_revalidated() -> None:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    digest = action_digest("task.complete.v1", {"task_id": "abc", "version": 4})
    request = ApprovalRequest(
        request_id=uuid4(),
        instance_id=uuid4(),
        requested_by_user_id=uuid4(),
        step_key="approve",
        action_digest=digest,
        risk="high",
        required_approvals=1,
        expires_at=now + timedelta(hours=1),
        policy_version=3,
    )
    decision = ApprovalDecision(
        decision_id=uuid4(),
        request_id=request.request_id,
        approver_id=uuid4(),
        approved=True,
        action_digest=digest,
        decided_at=now,
    )
    require_approval(request, (decision,), now=now, action_digest_value=digest, authorized=True)
    with pytest.raises(ApprovalError, match="digest"):
        require_approval(
            request, (decision,), now=now, action_digest_value="0" * 64, authorized=True
        )


def test_self_approval_does_not_satisfy_quorum() -> None:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    actor = uuid4()
    digest = action_digest("task.complete.v1", {"task_id": "abc"})
    request = ApprovalRequest(
        request_id=uuid4(),
        instance_id=uuid4(),
        requested_by_user_id=actor,
        step_key="approve",
        action_digest=digest,
        risk="high",
        required_approvals=1,
        expires_at=now + timedelta(hours=1),
        policy_version=1,
    )
    decision = ApprovalDecision(
        decision_id=uuid4(),
        request_id=request.request_id,
        approver_id=actor,
        approved=True,
        action_digest=digest,
        decided_at=now,
    )
    with pytest.raises(ApprovalError, match="quorum"):
        require_approval(
            request,
            (decision,),
            now=now,
            action_digest_value=digest,
            authorized=True,
        )
    with pytest.raises(ApprovalError, match="authorization"):
        require_approval(
            request, (decision,), now=now, action_digest_value=digest, authorized=False
        )
    with pytest.raises(ApprovalError, match="expired"):
        require_approval(
            request,
            (decision,),
            now=now + timedelta(hours=2),
            action_digest_value=digest,
            authorized=True,
        )


def test_digest_is_canonical_and_compensation_is_explicit() -> None:
    assert action_digest("x.v1", {"b": 2, "a": 1}) == action_digest("x.v1", {"a": 1, "b": 2})
    with pytest.raises(ValueError, match="compensation"):
        WorkflowStep(
            key="x", kind=StepKind.COMMAND, reference="task.complete.v1", compensation_reference=""
        )
