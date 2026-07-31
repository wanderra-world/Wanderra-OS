"""Google Drive adapter confined to the integration SDK boundary."""

from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime
from typing import Protocol

from docx import Document
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from pypdf import PdfReader

from app.capability_routing.credentials import ManagedConnectionCredentialLoader
from app.provider_capabilities.common import (
    CanonicalErrorCategory,
    ExtensionEnvelope,
    OpaqueCursor,
    Page,
    ProviderCapabilityError,
    VersionPrecondition,
)
from app.provider_capabilities.storage import (
    StorageContent,
    StorageObject,
    StorageText,
)
from app.storage_capability.contracts import StorageResourceObserver

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FILE_FIELDS = (
    "id,name,mimeType,size,version,modifiedTime,createdTime,md5Checksum,"
    "parents,description,starred,webViewLink,trashed"
)


class DriveApi(Protocol):
    async def object_page(
        self, *, query: str | None, limit: int, cursor: str | None
    ) -> dict[str, object]: ...
    async def metadata(self, external_id: str) -> dict[str, object]: ...
    async def content(self, external_id: str, export_media_type: str | None = None) -> bytes: ...
    async def create(
        self, body: dict[str, object], content: bytes, media_type: str
    ) -> dict[str, object]: ...
    async def update(
        self,
        external_id: str,
        body: dict[str, object] | None,
        content: bytes | None,
        media_type: str | None,
        precondition: str,
    ) -> dict[str, object]: ...
    async def delete(self, external_id: str, precondition: str) -> None: ...


class GoogleDriveApi:
    def __init__(self, resource: object):
        self._resource = resource

    def _files(self):
        return self._resource.files()  # type: ignore[attr-defined,no-any-return]

    async def object_page(self, *, query, limit, cursor):
        args = {
            "pageSize": limit,
            "fields": f"nextPageToken,files({FILE_FIELDS})",
            "orderBy": "modifiedTime desc",
        }
        if query:
            args["q"] = query
        if cursor:
            args["pageToken"] = cursor
        return await asyncio.to_thread(lambda: self._files().list(**args).execute())

    async def metadata(self, external_id):
        return await asyncio.to_thread(
            lambda: self._files().get(fileId=external_id, fields=FILE_FIELDS).execute()
        )

    async def content(self, external_id, export_media_type=None):
        request = (
            self._files().export_media(fileId=external_id, mimeType=export_media_type)
            if export_media_type
            else self._files().get_media(fileId=external_id)
        )

        def download():
            target = io.BytesIO()
            loader = MediaIoBaseDownload(target, request)
            done = False
            while not done:
                _, done = loader.next_chunk()
            return target.getvalue()

        return await asyncio.to_thread(download)

    async def create(self, body, content, media_type):
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=media_type, resumable=False)
        return await asyncio.to_thread(
            lambda: self._files().create(body=body, media_body=media, fields=FILE_FIELDS).execute()
        )

    async def update(self, external_id, body, content, media_type, precondition):
        media = (
            MediaIoBaseUpload(io.BytesIO(content), mimetype=media_type, resumable=False)
            if content is not None and media_type
            else None
        )
        request = self._files().update(
            fileId=external_id, body=body, media_body=media, fields=FILE_FIELDS
        )
        request.headers["If-Match"] = precondition
        return await asyncio.to_thread(request.execute)

    async def delete(self, external_id, precondition):
        request = self._files().delete(fileId=external_id)
        request.headers["If-Match"] = precondition
        await asyncio.to_thread(request.execute)


async def build_google_drive_api(serialized_credential: bytes) -> DriveApi:
    credentials = Credentials.from_authorized_user_info(json.loads(serialized_credential))
    return GoogleDriveApi(
        await asyncio.to_thread(
            build, "drive", "v3", credentials=credentials, cache_discovery=False
        )
    )


ManagedDriveCredentialLoader = ManagedConnectionCredentialLoader


class GoogleDriveManagedPortFactory:
    def __init__(self, credentials, builder=build_google_drive_api, observer=None):
        self._credentials = credentials
        self._builder = builder
        self._observer = observer

    async def canonical_port(self):
        return GoogleDriveAdapter(
            await self._builder(await self._credentials.load()), self._observer
        )


class GoogleDriveAdapter:
    def __init__(self, api: DriveApi, observer: StorageResourceObserver | None = None):
        self._api = api
        self._observer = observer

    async def list_objects(self, request):
        return await self._page(None, request.page.limit, request.page.cursor)

    async def search_objects(self, request):
        escaped = request.query.replace("\\", "\\\\").replace("'", "\\'")
        return await self._page(
            f"name contains '{escaped}' or fullText contains '{escaped}'",
            request.page.limit,
            request.page.cursor,
        )

    async def _page(self, query, limit, cursor):
        try:
            raw = await self._api.object_page(
                query=query, limit=limit, cursor=cursor.value if cursor else None
            )
            values = []
            for item in raw.get("files", []):
                values.append(await self._observed(item))
            token = raw.get("nextPageToken")
            return Page(tuple(values), OpaqueCursor(token) if token else None)
        except ProviderCapabilityError:
            raise
        except Exception as error:
            raise self._safe(error) from error

    async def read_metadata(self, external_id):
        return await self._observed(await self._api.metadata(external_id))

    async def download(self, external_id):
        metadata = await self.read_metadata(external_id)
        export = "text/plain" if metadata.media_type == GOOGLE_DOC_MIME else None
        return StorageContent(
            metadata, await self._api.content(external_id, export), export or metadata.media_type
        )

    async def read_text(self, external_id):
        value = await self.download(external_id)
        if value.metadata.media_type == GOOGLE_DOC_MIME:
            text = value.content.decode(errors="replace")
        elif value.metadata.media_type == PDF_MIME:
            text = "\n".join(
                p.extract_text() or "" for p in PdfReader(io.BytesIO(value.content)).pages
            )
        elif value.metadata.media_type == DOCX_MIME:
            text = "\n".join(p.text for p in Document(io.BytesIO(value.content)).paragraphs)
        else:
            raise ProviderCapabilityError(
                CanonicalErrorCategory.UNSUPPORTED_CAPABILITY,
                "This storage object has no supported text projection.",
            )
        return StorageText(value.metadata, text)

    async def upload(self, item, context):
        del context
        body = {"name": item.name}
        if item.parent_external_id:
            body["parents"] = [item.parent_external_id]
        if item.description is not None:
            body["description"] = item.description
        created = await self._api.create(body, item.content, item.media_type)
        return await self.read_metadata(str(created["id"]))

    async def update_metadata(self, external_id, changes, context):
        p = self._pre(context.precondition)
        body = {
            k: v
            for k, v in {
                "name": changes.name,
                "description": changes.description,
                "starred": changes.starred,
            }.items()
            if v is not None
        }
        await self._api.update(external_id, body, None, None, p)
        return await self.read_metadata(external_id)

    async def update_content(self, external_id, content, media_type, context):
        await self._api.update(
            external_id, None, content, media_type, self._pre(context.precondition)
        )
        return await self.read_metadata(external_id)

    async def delete(self, external_id, context):
        await self._api.delete(external_id, self._pre(context.precondition))
        try:
            await self._api.metadata(external_id)
        except ProviderCapabilityError as error:
            if error.category is CanonicalErrorCategory.NOT_FOUND:
                return
            raise
        raise ProviderCapabilityError(
            CanonicalErrorCategory.CONFLICT, "Storage deletion verification failed."
        )

    async def _observed(self, raw):
        item = self._object(raw)
        if self._observer:
            await self._observer.observe(item)
        return item

    @staticmethod
    def _object(raw):
        version = raw.get("version") or raw.get("md5Checksum")
        if version is None:
            raise ValueError("Provider object version is required.")

        def timestamp(value: object) -> datetime | None:
            return datetime.fromisoformat(str(value)) if value else None

        return StorageObject(
            str(raw["id"]),
            str(raw.get("name", "")),
            str(raw.get("mimeType", "application/octet-stream")),
            int(raw["size"]) if raw.get("size") else None,
            str(version),
            timestamp(raw.get("modifiedTime")),
            timestamp(raw.get("createdTime")),
            str(raw["md5Checksum"]) if raw.get("md5Checksum") else None,
            tuple(raw.get("parents", [])),
            str(raw["description"]) if raw.get("description") is not None else None,
            ExtensionEnvelope({"google.drive/starred": bool(raw["starred"])})
            if "starred" in raw
            else ExtensionEnvelope({}),
        )

    @staticmethod
    def _pre(value: VersionPrecondition | None):
        if value is None:
            raise ValueError("A version precondition is required.")
        return value.etag or value.version or ""

    @staticmethod
    def _safe(error):
        status = getattr(error, "status_code", None) or getattr(
            getattr(error, "resp", None), "status", None
        )
        category = {
            401: CanonicalErrorCategory.AUTHENTICATION,
            403: CanonicalErrorCategory.AUTHORIZATION,
            404: CanonicalErrorCategory.NOT_FOUND,
            409: CanonicalErrorCategory.CONFLICT,
            412: CanonicalErrorCategory.CONFLICT,
            429: CanonicalErrorCategory.RATE_LIMIT,
        }.get(status, CanonicalErrorCategory.TRANSIENT)
        return ProviderCapabilityError(category, "Storage provider operation failed.")
