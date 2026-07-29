import pytest

from app.integrations.google_oauth import (
    CALENDAR_SCOPES,
    DRIVE_SCOPES,
    GMAIL_SCOPES,
    accepted_incremental_scopes,
)


def test_calendar_incremental_auth_accepts_existing_gmail_scopes() -> None:
    returned = " ".join(sorted(CALENDAR_SCOPES | GMAIL_SCOPES))

    assert set(accepted_incremental_scopes(returned, CALENDAR_SCOPES) or []) == (
        CALENDAR_SCOPES | GMAIL_SCOPES
    )


def test_drive_incremental_auth_accepts_gmail_and_calendar_scopes() -> None:
    returned = " ".join(sorted(DRIVE_SCOPES | CALENDAR_SCOPES | GMAIL_SCOPES))

    assert set(accepted_incremental_scopes(returned, DRIVE_SCOPES) or []) == (
        DRIVE_SCOPES | CALENDAR_SCOPES | GMAIL_SCOPES
    )


def test_incremental_auth_rejects_missing_required_scope() -> None:
    with pytest.raises(ValueError, match="required"):
        accepted_incremental_scopes(" ".join(sorted(GMAIL_SCOPES)), CALENDAR_SCOPES)


def test_incremental_auth_rejects_unexpected_scope() -> None:
    returned = " ".join(
        CALENDAR_SCOPES | {"https://www.googleapis.com/auth/contacts"}
    )

    with pytest.raises(ValueError, match="unexpected"):
        accepted_incremental_scopes(returned, CALENDAR_SCOPES)
