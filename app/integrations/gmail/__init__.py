"""Gmail provider adapter and Phase 1 compatibility integration."""

from app.integrations.gmail.credential_store import (
    GmailCredentialSink,
    GmailRefreshingCredentialLoader,
)
from app.integrations.gmail.oauth import GmailOAuthProtocol
from app.integrations.gmail.service import GmailService
from app.integrations.gmail.workspace_oauth import GmailWorkspaceOAuthService

__all__ = [
    "GmailCredentialSink",
    "GmailOAuthProtocol",
    "GmailRefreshingCredentialLoader",
    "GmailService",
    "GmailWorkspaceOAuthService",
]
