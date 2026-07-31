"""Provider SDK confinement boundary.

Concrete adapters may hold provider SDK clients internally, but only these canonical
ports and descriptors can cross into application code.
"""

from __future__ import annotations

from typing import Protocol

from app.provider_capabilities.calendar import CalendarPort
from app.provider_capabilities.common import CapabilityDescriptor
from app.provider_capabilities.email import EmailPort
from app.provider_capabilities.storage import StoragePort


class ProviderSDKBoundary(Protocol):
    @property
    def provider_key(self) -> str: ...

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]: ...

    @property
    def email(self) -> EmailPort: ...

    @property
    def calendar(self) -> CalendarPort: ...

    @property
    def storage(self) -> StoragePort: ...
