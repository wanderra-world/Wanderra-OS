"""Canonical provider-neutral capability contracts for H2-05."""

from app.provider_capabilities.calendar import CalendarPort
from app.provider_capabilities.common import CapabilityRegistry
from app.provider_capabilities.email import EmailPort
from app.provider_capabilities.sdk import ProviderSDKBoundary
from app.provider_capabilities.storage import StoragePort

__all__ = [
    "CalendarPort",
    "CapabilityRegistry",
    "EmailPort",
    "ProviderSDKBoundary",
    "StoragePort",
]
