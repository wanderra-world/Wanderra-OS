from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from docx import Document

from app.integrations.drive.adapter import (
    DOCX_MIME,
    GOOGLE_DOC_MIME,
    GoogleDriveAdapter,
)
from app.provider_capabilities.common import MutationContext, VersionPrecondition
from app.provider_capabilities.storage import (
    StorageListRequest,
    StorageObjectCreate,
    StorageObjectPatch,
    StorageSearchRequest,
)


class FakeDriveApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.deleted = False

    async def object_page(self, *, query, limit, cursor):
        self.calls.append(("page", (query, limit, cursor)))
        return {"files": [self.raw()], "nextPageToken": "next"}

    async def metadata(self, external_id):
        self.calls.append(("metadata", external_id))
        if self.deleted:
            from app.provider_capabilities.common import (
                CanonicalErrorCategory,
                ProviderCapabilityError,
            )

            raise ProviderCapabilityError(CanonicalErrorCategory.NOT_FOUND, "Not found.")
        return self.raw(external_id)

    async def content(self, external_id, export_media_type=None):
        self.calls.append(("content", (external_id, export_media_type)))
        return b"Atlas document"

    async def create(self, body, content, media_type):
        self.calls.append(("create", (body, content, media_type)))
        return self.raw("created")

    async def update(self, external_id, body, content, media_type, precondition):
        self.calls.append(("update", (external_id, body, content, media_type, precondition)))
        return self.raw(external_id)

    async def delete(self, external_id, precondition):
        self.calls.append(("delete", (external_id, precondition)))
        self.deleted = True

    @staticmethod
    def raw(external_id="file-1", media_type="text/plain"):
        return {
            "id": external_id,
            "name": "Atlas.txt",
            "mimeType": media_type,
            "size": "14",
            "version": "7",
            "md5Checksum": "abc",
            "modifiedTime": "2026-07-31T12:00:00Z",
            "createdTime": "2026-07-30T12:00:00Z",
            "parents": ["root"],
            "description": "Atlas",
            "starred": True,
        }


@pytest.mark.asyncio
async def test_adapter_translates_list_search_metadata_and_download() -> None:
    api = FakeDriveApi()
    adapter = GoogleDriveAdapter(api)
    page = await adapter.list_objects(StorageListRequest())
    searched = await adapter.search_objects(StorageSearchRequest("Atlas"))
    metadata = await adapter.read_metadata("file-1")
    content = await adapter.download("file-1")
    assert page.items[0].version == "7" and page.items[0].checksum == "abc"
    assert page.items[0].modified_at == datetime(2026, 7, 31, 12, tzinfo=UTC)
    assert searched.items[0] == metadata and content.content == b"Atlas document"
    assert api.calls[1][1][0] == "name contains 'Atlas' or fullText contains 'Atlas'"


@pytest.mark.asyncio
async def test_adapter_reads_google_docs_pdf_and_docx_without_persisting_content() -> None:
    api = FakeDriveApi()
    adapter = GoogleDriveAdapter(api)
    api.raw = lambda external_id="file-1": FakeDriveApi.raw(external_id, GOOGLE_DOC_MIME)
    assert (await adapter.read_text("doc")).text == "Atlas document"
    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph("Atlas DOCX")
    document.save(buffer)
    api.raw = lambda external_id="file-1": FakeDriveApi.raw(external_id, DOCX_MIME)
    api.content = lambda external_id, export_media_type=None: _value(buffer.getvalue())
    assert "Atlas DOCX" in (await adapter.read_text("docx")).text


async def _value(value):
    return value


@pytest.mark.asyncio
async def test_mutations_require_versions_and_verify_provider_state() -> None:
    api = FakeDriveApi()
    adapter = GoogleDriveAdapter(api)
    created = await adapter.upload(
        StorageObjectCreate("a.txt", b"a", "text/plain"), MutationContext("c")
    )
    assert created.external_id == "created" and api.calls[1] == ("metadata", "created")
    context = MutationContext("u", VersionPrecondition(version="7"))
    await adapter.update_metadata("file-1", StorageObjectPatch(name="b.txt"), context)
    await adapter.update_content("file-1", b"b", "text/plain", context)
    await adapter.delete("file-1", MutationContext("d", VersionPrecondition(version="7")))
    assert [call[0] for call in api.calls].count("metadata") == 4
    with pytest.raises(Exception, match="precondition"):
        await GoogleDriveAdapter(FakeDriveApi()).delete("file-1", MutationContext("blind"))
