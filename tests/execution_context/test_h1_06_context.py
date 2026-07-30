"""Unit tests for immutable request, actor, tenant, and repository context."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.execution_context import (
    ActorContext,
    ContextBoundRepository,
    ExecutionContext,
    ExecutionContextError,
    ExecutionContextRequiredError,
    ExecutionContextService,
    RequestContext,
    TenantContext,
    current_execution_context,
)


def make_context() -> ExecutionContext:
    return ExecutionContext(
        request=RequestContext(
            request_id="request-1",
            correlation_id="correlation-1",
        ),
        actor=ActorContext(
            actor_id=uuid4(),
            session_id=uuid4(),
            membership_id=uuid4(),
            authorization_decision_id=uuid4(),
        ),
        tenant=TenantContext(
            organization_id=uuid4(),
            workspace_id=uuid4(),
            cell_id=uuid4(),
        ),
    )


def test_context_contract_is_immutable_versioned_and_validated() -> None:
    context = make_context()
    assert context.version == 1
    with pytest.raises(AttributeError):
        context.version = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="request_id"):
        RequestContext(request_id=" ", correlation_id="correlation")
    with pytest.raises(ValueError, match="unsupported"):
        ExecutionContext(
            request=context.request,
            actor=context.actor,
            tenant=context.tenant,
            version=2,
        )


def test_request_scope_is_nested_and_always_reset() -> None:
    first = make_context()
    second = make_context()
    service = ExecutionContextService()

    with pytest.raises(ExecutionContextError, match="required"):
        current_execution_context()
    with service.bind(first):
        assert current_execution_context() == first
        with service.bind(second):
            assert current_execution_context() == second
        assert current_execution_context() == first
    with pytest.raises(ExecutionContextError, match="required"):
        current_execution_context()


def test_audit_references_are_traceable_and_non_sensitive() -> None:
    context = make_context()
    references = context.audit_references()
    assert references == {
        "request_id": "request-1",
        "correlation_id": "correlation-1",
        "authorization_decision_id": str(
            context.actor.authorization_decision_id
        ),
        "execution_context_version": "1",
    }
    assert "session_id" not in references
    assert "membership_id" not in references


def test_repository_rejects_missing_mismatched_and_cross_workspace_context() -> None:
    context = make_context()
    other = make_context()

    class FakeSession:
        def __init__(self) -> None:
            self.info: dict[str, object] = {}

    session = FakeSession()
    repository = ContextBoundRepository(session, context)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContextRequiredError, match="required"):
        repository.require_workspace(context.tenant.workspace_id)

    session.info["atlas.execution_context"] = other
    with pytest.raises(ExecutionContextRequiredError, match="do not match"):
        repository.require_workspace(context.tenant.workspace_id)

    session.info["atlas.execution_context"] = context
    with pytest.raises(ExecutionContextRequiredError, match="cross-workspace"):
        repository.require_workspace(other.tenant.workspace_id)
    repository.require_workspace(context.tenant.workspace_id)
