"""Provider-neutral IP-01 integration composition boundary."""

from app.integration_layer.contracts import (
    IntegrationAuthorizationError,
    IntegrationCapabilityError,
    IntegrationCredentialError,
    IntegrationResolution,
    IntegrationResolutionError,
    IntegrationResolutionRequest,
    IntegrationStateError,
)
from app.integration_layer.repository import IntegrationRepository
from app.integration_layer.service import IntegrationResolver

__all__ = [
    "IntegrationAuthorizationError",
    "IntegrationCapabilityError",
    "IntegrationCredentialError",
    "IntegrationRepository",
    "IntegrationResolution",
    "IntegrationResolutionError",
    "IntegrationResolutionRequest",
    "IntegrationResolver",
    "IntegrationStateError",
]
