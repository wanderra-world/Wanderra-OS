from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from app.capability_routing.contracts import CapabilityRoute
from app.provider_capabilities.storage import StorageObject, StoragePort

StorageRoute = CapabilityRoute


class StorageOperation(StrEnum):
    LIST = "list"
    SEARCH = "search"
    METADATA = "metadata"
    DOWNLOAD = "download"
    READ_TEXT = "read_text"
    UPLOAD = "upload"
    UPDATE_METADATA = "update_metadata"
    UPDATE_CONTENT = "update_content"
    DELETE = "delete"


class CanonicalStoragePortFactory(Protocol):
    async def canonical_port(self) -> StoragePort: ...


class StorageRoutingStore(Protocol):
    async def route(self) -> StorageRoute: ...
    async def record_comparison(self, operation: StorageOperation, equivalent: bool) -> None: ...


class StorageResourceObserver(Protocol):
    async def observe(self, item: StorageObject) -> None: ...
