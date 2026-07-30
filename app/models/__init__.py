"""SQLAlchemy ORM models.

Import every model here to make it discoverable by Alembic migrations.
"""

from app.identity.lifecycle_models import (
    IdentityLifecycleToken,
    IdentitySession,
    SecurityNotification,
)
from app.identity.models import ExternalIdentityLink, User
from app.memberships.models import FixedMembershipRole, WorkspaceMembership
from app.models.calendar import CalendarCredential, CalendarOAuthState
from app.models.drive import DriveCredential, DriveFileMetadata, DriveOAuthState
from app.models.gmail import GmailCredential, GmailOAuthState
from app.models.memory import Conversation, ConversationMessage, Project
from app.tenancy.models import (
    AuditEvent,
    Cell,
    Organization,
    OrganizationMembership,
    OutboxEvent,
    Workspace,
)

__all__ = [
    "CalendarCredential",
    "CalendarOAuthState",
    "AuditEvent",
    "Cell",
    "Conversation",
    "ConversationMessage",
    "DriveCredential",
    "DriveFileMetadata",
    "DriveOAuthState",
    "ExternalIdentityLink",
    "FixedMembershipRole",
    "IdentityLifecycleToken",
    "IdentitySession",
    "GmailCredential",
    "GmailOAuthState",
    "Organization",
    "OrganizationMembership",
    "OutboxEvent",
    "Project",
    "SecurityNotification",
    "User",
    "Workspace",
    "WorkspaceMembership",
]
