"""Managed KMS infrastructure adapters for Atlas encryption."""

from app.core.config import Settings
from app.encryption.contracts import KeyProvider
from app.integrations.kms.google_cloud import GoogleCloudKmsKeyProvider


def key_provider_from_settings(settings: Settings) -> KeyProvider:
    """Select the approved production KMS adapter without local-key fallback."""
    if settings.atlas_kms_provider == "google_cloud_kms":
        return GoogleCloudKmsKeyProvider.from_default_credentials()
    raise RuntimeError("ATLAS_KMS_PROVIDER must select an approved managed KMS")


__all__ = ["GoogleCloudKmsKeyProvider", "key_provider_from_settings"]
