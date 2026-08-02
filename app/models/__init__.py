"""SQLAlchemy ORM models.

Import every model here to make it discoverable by Alembic migrations.
"""

from app.authorization.models import Permission, RolePermission
from app.calendar_capability.models import (
    CalendarCapabilityRoute,
    CalendarShadowComparison,
)
from app.connection_credentials.models import (
    ConnectionCredential,
    CredentialMigrationInventory,
)
from app.connection_cutover.models import (
    CapabilityCutoverEvidence,
    ConnectionBackfillEvidence,
)
from app.connections.models import (
    Connection,
    ConnectionCapabilityGrant,
    ConnectionKind,
    ConnectionKindCapability,
    ProviderCapability,
    ProviderRegistryEntry,
)
from app.documents.models import (
    Document,
    DocumentChunk,
    DocumentDeletion,
    DocumentDerivative,
    DocumentVersion,
)
from app.email_capability.models import EmailCapabilityRoute, EmailShadowComparison
from app.encryption.models import EncryptedEnvelope
from app.identity.lifecycle_models import (
    IdentityLifecycleToken,
    IdentitySession,
    SecurityNotification,
)
from app.identity.models import ExternalIdentityLink, User
from app.jobs.models import (
    JobAttempt,
    JobDeadLetter,
    JobDefinition,
    JobInstance,
    JobOperatorControl,
    JobSchedule,
)
from app.knowledge.models import (
    KnowledgeClaim,
    KnowledgeEvidence,
    KnowledgeRelation,
    KnowledgeSourceDisposition,
    TimelineCheckpoint,
    TimelineEntry,
)
from app.memberships.models import FixedMembershipRole, Role, WorkspaceMembership
from app.memory.governed_models import (
    GovernedMemoryDisposition,
    GovernedMemoryFeedback,
    GovernedMemoryItem,
    GovernedMemorySource,
)
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
from app.resource_graph.models import (
    Resource,
    ResourceAttachment,
    ResourceExternalLink,
    ResourceGrant,
    ResourceNote,
    ResourceOwnership,
    ResourceProjection,
    ResourceRelationship,
    ResourceTag,
)
from app.storage_capability.models import StorageCapabilityRoute, StorageShadowComparison
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
    "CalendarCapabilityRoute",
    "CalendarOAuthState",
    "CalendarShadowComparison",
    "AuditEvent",
    "Cell",
    "CommandIdempotency",
    "Connection",
    "ConnectionCredential",
    "ConnectionBackfillEvidence",
    "ConnectionCapabilityGrant",
    "ConnectionKind",
    "ConnectionKindCapability",
    "ConsumerSequence",
    "CapabilityCutoverEvidence",
    "CredentialMigrationInventory",
    "Conversation",
    "ConversationMessage",
    "DriveCredential",
    "DriveFileMetadata",
    "DriveOAuthState",
    "Document",
    "DocumentChunk",
    "DocumentDeletion",
    "DocumentDerivative",
    "DocumentVersion",
    "EncryptedEnvelope",
    "EmailCapabilityRoute",
    "EmailShadowComparison",
    "ExternalIdentityLink",
    "EventQuarantine",
    "FixedMembershipRole",
    "IdentityLifecycleToken",
    "IdentitySession",
    "InboxEvent",
    "JobAttempt",
    "JobDeadLetter",
    "JobDefinition",
    "JobInstance",
    "JobOperatorControl",
    "JobSchedule",
    "KnowledgeClaim",
    "KnowledgeEvidence",
    "KnowledgeRelation",
    "KnowledgeSourceDisposition",
    "GmailCredential",
    "GmailOAuthState",
    "GovernedMemoryDisposition",
    "GovernedMemoryFeedback",
    "GovernedMemoryItem",
    "GovernedMemorySource",
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
    "Resource",
    "ResourceAttachment",
    "ResourceExternalLink",
    "ResourceGrant",
    "ResourceNote",
    "ResourceOwnership",
    "ResourceProjection",
    "ResourceRelationship",
    "ResourceTag",
    "SecurityNotification",
    "TimelineCheckpoint",
    "TimelineEntry",
    "StorageCapabilityRoute",
    "StorageShadowComparison",
    "User",
    "Workspace",
    "WorkspaceClosure",
    "WorkspaceDataGovernance",
    "WorkspaceExport",
    "WorkspaceMembership",
]
