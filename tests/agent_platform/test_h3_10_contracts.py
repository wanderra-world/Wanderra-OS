import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.agent_platform.contracts import (
    AgentManifest,
    AgentPlatformError,
    Budget,
    Delegation,
    ExecutionOutcome,
    PlanProposal,
    PlanStatus,
    PlanStep,
    RiskLevel,
    ToolManifest,
    action_digest,
    attenuate_delegation,
    reserve_budget,
    validate_execution,
    validate_plan,
    verify_result,
)


def tool(*, key: str = "task.read", risk: RiskLevel = RiskLevel.LOW) -> ToolManifest:
    return ToolManifest(
        tool_id=uuid4(),
        key=key,
        version=1,
        command_reference=f"{key}.v1",
        permission_key=f"{key}.execute",
        risk=risk,
        input_schema_version=1,
        output_schema_version=1,
        enabled=True,
    )


def manifest(allowed: tuple[str, ...] = ("task",)) -> AgentManifest:
    return AgentManifest(
        manifest_id=uuid4(),
        version=1,
        name="synthetic-conformance",
        purpose="Exercise platform contracts only",
        owner_user_id=uuid4(),
        allowed_tool_classes=allowed,
        risk_ceiling=RiskLevel.HIGH,
        budget=Budget(max_tokens=1000, max_cost_micros=5000, max_tool_calls=3, max_seconds=60),
        model_policy_key="private.internal.v1",
        evaluation_set_key="synthetic.h3-10.v1",
        input_schema_version=1,
        output_schema_version=1,
        enabled=True,
    )


def plan(value: ToolManifest, *, manifest_id: uuid.UUID | None = None) -> PlanProposal:
    return PlanProposal(
        plan_id=uuid4(),
        version=1,
        manifest_id=manifest_id or uuid4(),
        manifest_version=1,
        model_policy_key="private.internal.v1",
        classification="internal",
        evidence_references=("resource:abc",),
        assumptions=("synthetic input is available",),
        estimated_tokens=100,
        estimated_cost_micros=200,
        steps=(
            PlanStep(
                key="read",
                tool_key=value.key,
                tool_version=value.version,
                input_payload={"resource_id": "abc"},
                expected_resource_version=2,
                expected_outcome="resource returned",
                verification_reference="resource.read.verify.v1",
                risk=value.risk,
            ),
        ),
    )


def test_manifest_and_tool_registry_are_versioned_inert_and_confined() -> None:
    value = tool()
    assert value.command_reference == "task.read.v1"
    with pytest.raises(ValueError, match="application command"):
        ToolManifest(
            tool_id=uuid4(),
            key="bad",
            version=1,
            command_reference="python:call",
            permission_key="bad.execute",
            risk=RiskLevel.LOW,
            input_schema_version=1,
            output_schema_version=1,
            enabled=True,
        )
    with pytest.raises(Exception):
        value.version = 2


def test_delegation_can_only_attenuate_permissions_and_expiry() -> None:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    parent = Delegation(
        delegation_id=uuid4(),
        actor_id=uuid4(),
        permissions=("task.read.execute", "task.write.execute"),
        risk_ceiling=RiskLevel.HIGH,
        expires_at=now + timedelta(hours=2),
    )
    child = attenuate_delegation(
        parent,
        delegation_id=uuid4(),
        permissions=("task.read.execute",),
        risk_ceiling=RiskLevel.LOW,
        expires_at=now + timedelta(hours=1),
    )
    assert child.permissions == ("task.read.execute",)
    with pytest.raises(AgentPlatformError, match="amplify"):
        attenuate_delegation(
            parent,
            delegation_id=uuid4(),
            permissions=("admin.grant",),
            risk_ceiling=RiskLevel.LOW,
            expires_at=child.expires_at,
        )


def test_plan_is_inert_typed_evidence_linked_and_fails_closed() -> None:
    registered = tool()
    agent = manifest()
    proposal = plan(registered, manifest_id=agent.manifest_id)
    assert proposal.status is PlanStatus.PROPOSED
    validated = validate_plan(proposal, agent, {registered.key: registered})
    assert validated.status is PlanStatus.VALIDATED
    with pytest.raises(AgentPlatformError, match="unregistered"):
        validate_plan(
            proposal.model_copy(
                update={"steps": (proposal.steps[0].model_copy(update={"tool_key": "unknown"}),)}
            ),
            agent,
            {},
        )


def test_budget_reservation_and_action_digest_are_deterministic() -> None:
    limits = Budget(max_tokens=1000, max_cost_micros=5000, max_tool_calls=2, max_seconds=60)
    remaining = reserve_budget(limits, tokens=100, cost_micros=250, tool_calls=1, seconds=5)
    assert remaining.max_tokens == 900
    with pytest.raises(AgentPlatformError, match="budget"):
        reserve_budget(remaining, tokens=0, cost_micros=0, tool_calls=2, seconds=0)
    assert action_digest("task.read.v1", {"b": 2, "a": 1}, 3) == action_digest(
        "task.read.v1", {"a": 1, "b": 2}, 3
    )


def test_results_are_verified_or_explicitly_uncertain() -> None:
    assert verify_result("ok", verification_passed=True) is ExecutionOutcome.VERIFIED
    assert verify_result("ambiguous", verification_passed=None) is ExecutionOutcome.UNCERTAIN
    assert verify_result("bad", verification_passed=False) is ExecutionOutcome.FAILED


def test_prompt_like_or_sensitive_plan_input_is_rejected() -> None:
    value = tool()
    with pytest.raises(ValueError, match="sensitive"):
        PlanStep(
            key="bad",
            tool_key=value.key,
            tool_version=1,
            input_payload={"access_token": "never"},
            expected_resource_version=1,
            expected_outcome="never",
            verification_reference="task.read.verify.v1",
            risk=RiskLevel.LOW,
        )


def test_execution_revalidates_delegation_risk_authorization_and_approval() -> None:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    registered = tool(risk=RiskLevel.HIGH)
    step = plan(registered).steps[0].model_copy(update={"approval_id": uuid4()})
    agent = manifest()
    delegation = Delegation(
        delegation_id=uuid4(),
        actor_id=uuid4(),
        permissions=(registered.permission_key,),
        risk_ceiling=RiskLevel.HIGH,
        expires_at=now + timedelta(minutes=5),
    )
    digest = validate_execution(
        step,
        registered,
        agent,
        delegation,
        now=now,
        authorized=True,
        approval_valid=True,
    )
    assert digest == action_digest(
        registered.command_reference, step.input_payload, step.expected_resource_version
    )
    with pytest.raises(AgentPlatformError, match="approval"):
        validate_execution(
            step,
            registered,
            agent,
            delegation,
            now=now,
            authorized=True,
            approval_valid=False,
        )
    with pytest.raises(AgentPlatformError, match="disabled"):
        validate_execution(
            step,
            registered,
            agent.model_copy(update={"enabled": False}),
            delegation,
            now=now,
            authorized=True,
            approval_valid=True,
        )
