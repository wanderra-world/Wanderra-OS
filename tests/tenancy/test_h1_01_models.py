"""Unit-level schema contract tests for H1-01."""

from sqlalchemy import ForeignKeyConstraint, PrimaryKeyConstraint

import app.models  # noqa: F401
from app.database.base import Base
from app.tenancy.models import (
    AuditEvent,
    Cell,
    Organization,
    OrganizationMembership,
    OutboxEvent,
    Workspace,
)


def test_h1_01_models_are_registered_in_the_canonical_metadata() -> None:
    expected_tables = {
        "audit_events",
        "cells",
        "organization_memberships",
        "organizations",
        "outbox_events",
        "workspaces",
    }

    assert expected_tables <= set(Base.metadata.tables)
    assert Cell.__table__ is Base.metadata.tables["cells"]
    assert Organization.__table__ is Base.metadata.tables["organizations"]
    assert OrganizationMembership.__table__ is Base.metadata.tables[
        "organization_memberships"
    ]
    assert Workspace.__table__ is Base.metadata.tables["workspaces"]
    assert AuditEvent.__table__ is Base.metadata.tables["audit_events"]
    assert OutboxEvent.__table__ is Base.metadata.tables["outbox_events"]


def test_workspace_identity_and_placement_are_explicit() -> None:
    workspace = Workspace.__table__

    assert set(workspace.primary_key.columns.keys()) == {"workspace_id"}
    assert {"workspace_id", "organization_id", "cell_id"} <= set(
        workspace.columns.keys()
    )
    assert any(
        set(constraint.columns.keys()) == {"workspace_id", "organization_id"}
        for constraint in workspace.constraints
    )


def test_tenant_event_tables_use_workspace_composite_keys_and_foreign_keys() -> None:
    for table in (AuditEvent.__table__, OutboxEvent.__table__):
        primary_key = next(
            constraint
            for constraint in table.constraints
            if isinstance(constraint, PrimaryKeyConstraint)
        )
        assert set(primary_key.columns.keys()) == {"workspace_id", "id"}

        workspace_foreign_key = next(
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        )
        assert set(workspace_foreign_key.columns.keys()) == {"workspace_id"}
        assert {
            element.target_fullname for element in workspace_foreign_key.elements
        } == {"workspaces.workspace_id"}


def test_h1_01_does_not_change_phase_one_model_tables() -> None:
    phase_one_tables = {
        "calendar_credentials",
        "calendar_oauth_states",
        "conversation_messages",
        "conversations",
        "drive_credentials",
        "drive_file_metadata",
        "drive_oauth_states",
        "gmail_credentials",
        "gmail_oauth_states",
        "projects",
        "users",
    }

    assert phase_one_tables <= set(Base.metadata.tables)
