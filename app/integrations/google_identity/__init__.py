"""Google Identity adapter for the provider-neutral Atlas operator-auth boundary."""

from app.integrations.google_identity.oidc import (
    GoogleOIDCConfiguration,
    GoogleOIDCError,
    GoogleOIDCProtocol,
)

__all__ = ["GoogleOIDCConfiguration", "GoogleOIDCError", "GoogleOIDCProtocol"]
