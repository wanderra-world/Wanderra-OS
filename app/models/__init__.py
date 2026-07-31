"""SQLAlchemy ORM models.

Import every model here to make it discoverable by Alembic migrations.
"""

from app.authorization.models import Permission, RolePermission
from app.connection_credentials.models import (
    ConnectionCredential,
    CredentialMigrationInventory,
)
from app.connections.models import (
    Connection,
    ConnectionCapabilityGrant,
    ConnectionKind,
    ConnectionKindCapability,
    ProviderCapability,
    ProviderRegistryEntry,
)
from app.email_capability.models import EmailCapabilityRoute, EmailShadowComparison
from app.encryption.models import EncryptedEnvelope
from app.identity.lifecycle_models import (
    IdentityLifecycleToken,
    IdentitySession,
    SecurityNotification,
)
from app.identity.models import ExternalIdentityLink, User
from app.memberships.models import FixedMembershipRole, Role, WorkspaceMembership
from app.messaging.models import (
    AggregateVersion,
    AuditChainHead,
    CommandIdempotency,
    ConsumerSequence,
    EventQuarantine,
    InboxEvent,
)
from app.models.calendar import CalendarCredential, CalendarOAuthState
from app.models.drive import DriveCredential, DriveFileMetadata, DriveOAuthState
from app.models.gmail import GmailCredential, GmailOAuthState
from app.models.memory import Conversation, ConversationMessage, Project
from app.oauth_transactions.models import OAuthTransaction
from app.provider_mirrors.models import (
    ProviderExternalReference,
    ProviderMirror,
    ProviderMirrorComparison,
    ProviderMirrorConflict,
)
from app.recovery.models import (
    RecoveryEvidence,
    WorkspaceClosure,
    WorkspaceDataGovernance,
    WorkspaceExport,
)
from app.tenancy.models import (
    AuditEvent,
    Cell,
    Organization,
    OrganizationMembership,
    OutboxEvent,
    Workspace,
)

__all__ = [
    "AggregateVersion",
    "AuditChainHead",
    "CalendarCredential",
    "CalendarOAuthState",
    "AuditEvent",
    "Cell",
    "CommandIdempotency",
    "Connection",
    "ConnectionCredential",
    "ConnectionCapabilityGrant",
    "ConnectionKind",
    "ConnectionKindCapability",
    "ConsumerSequence",
    "CredentialMigrationInventory",
    "Conversation",
    "ConversationMessage",
    "DriveCredential",
    "DriveFileMetadata",
    "DriveOAuthState",
    "EncryptedEnvelope",
    "EmailCapabilityRoute",
    "EmailShadowComparison",
    "ExternalIdentityLink",
    "EventQuarantine",
    "FixedMembershipRole",
    "IdentityLifecycleToken",
    "IdentitySession",
    "InboxEvent",
    "GmailCredential",
    "GmailOAuthState",
    "Organization",
    "OrganizationMembership",
    "OAuthTransaction",
    "OutboxEvent",
    "Project",
    "ProviderCapability",
    "ProviderExternalReference",
    "ProviderMirror",
    "ProviderMirrorComparison",
    "ProviderMirrorConflict",
    "ProviderRegistryEntry",
    "Permission",
    "Role",
    "RolePermission",
    "RecoveryEvidence",
    "SecurityNotification",
    "User",
    "Workspace",
    "WorkspaceClosure",
    "WorkspaceDataGovernance",
    "WorkspaceExport",
    "WorkspaceMembership",
]
