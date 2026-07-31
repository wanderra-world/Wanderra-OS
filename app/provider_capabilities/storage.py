"""Provider-neutral storage capability contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.provider_capabilities.common import (
    EMPTY_EXTENSIONS,
    ExtensionEnvelope,
    MutationContext,
    Page,
    PageRequest,
)


@dataclass(frozen=True, slots=True)
class StorageObject:
    external_id: str
    name: str
    media_type: str
    size: int | None
    version: str
    modified_at: datetime | None = None
    created_at: datetime | None = None
    checksum: str | None = None
    parent_external_ids: tuple[str, ...] = ()
    description: str | None = None
    extensions: ExtensionEnvelope = EMPTY_EXTENSIONS


@dataclass(frozen=True, slots=True)
class StorageContent:
    metadata: StorageObject
    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class StorageText:
    metadata: StorageObject
    text: str


@dataclass(frozen=True, slots=True)
class StorageListRequest:
    page: PageRequest = PageRequest()


@dataclass(frozen=True, slots=True)
class StorageSearchRequest:
    query: str
    page: PageRequest = PageRequest()


@dataclass(frozen=True, slots=True)
class StorageObjectCreate:
    name: str
    content: bytes
    media_type: str
    parent_external_id: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class StorageObjectPatch:
    name: str | None = None
    description: str | None = None
    starred: bool | None = None

    def __post_init__(self) -> None:
        if self.name is None and self.description is None and self.starred is None:
            raise ValueError("At least one storage metadata change is required.")


class StoragePort(Protocol):
    async def list_objects(self, request: StorageListRequest) -> Page[StorageObject]: ...
    async def search_objects(
        self, request: StorageSearchRequest
    ) -> Page[StorageObject]: ...
    async def read_metadata(self, external_id: str) -> StorageObject: ...
    async def download(self, external_id: str) -> StorageContent: ...
    async def read_text(self, external_id: str) -> StorageText: ...
    async def upload(
        self, item: StorageObjectCreate, context: MutationContext
    ) -> StorageObject: ...
    async def update_metadata(
        self,
        external_id: str,
        changes: StorageObjectPatch,
        context: MutationContext,
    ) -> StorageObject: ...
    async def update_content(
        self,
        external_id: str,
        content: bytes,
        media_type: str,
        context: MutationContext,
    ) -> StorageObject: ...
    async def delete(self, external_id: str, context: MutationContext) -> None: ...
