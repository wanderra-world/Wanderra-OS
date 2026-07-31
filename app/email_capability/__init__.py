"""Provider-neutral email routing and shadow verification."""

from app.email_capability.contracts import EmailOperation, EmailRoute
from app.email_capability.service import EmailCapabilityService

__all__ = ["EmailCapabilityService", "EmailOperation", "EmailRoute"]
