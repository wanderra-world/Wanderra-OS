"""Shared validation for Google's incremental OAuth scope responses."""

GMAIL_SCOPES = {
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
}
CALENDAR_SCOPES = {"https://www.googleapis.com/auth/calendar"}
DRIVE_SCOPES = {"https://www.googleapis.com/auth/drive"}
ALLOWED_SCOPES = GMAIL_SCOPES | CALENDAR_SCOPES | DRIVE_SCOPES


def accepted_incremental_scopes(
    returned_scope: str | None, required_scopes: set[str]
) -> list[str] | None:
    """Validate Google's returned grant and return it for OAuth session alignment."""
    if returned_scope is None:
        return None
    returned = set(returned_scope.split())
    if not required_scopes.issubset(returned):
        raise ValueError("Google OAuth did not grant all required scopes.")
    if not returned.issubset(ALLOWED_SCOPES):
        raise ValueError("Google OAuth returned an unexpected scope.")
    return sorted(returned)
