"""Google Drive OAuth, file operations, and text extraction."""

import asyncio
import base64
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet
from docx import Document
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.integrations.google_errors import execute_google_request
from app.integrations.google_oauth import DRIVE_SCOPES, accepted_incremental_scopes
from app.models.drive import DriveCredential, DriveFileMetadata, DriveOAuthState

SCOPES = sorted(DRIVE_SCOPES)
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FILE_FIELDS = (
    "id,name,mimeType,size,modifiedTime,createdTime,webViewLink,webContentLink,"
    "md5Checksum,parents,description,trashed,owners,shared"
)


class DriveConfigurationError(RuntimeError):
    pass


class DriveNotConnectedError(RuntimeError):
    pass


class UnsupportedDriveFileError(RuntimeError):
    pass


class DriveService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        if not self._has_oauth_client() or self.settings.gmail_credentials_encryption_key is None:
            raise DriveConfigurationError(
                "Google OAuth and credential encryption settings are required."
            )
        key = self.settings.gmail_credentials_encryption_key.get_secret_value().encode()
        self.fernet = Fernet(key)

    def _has_oauth_client(self) -> bool:
        return Path(self.settings.google_oauth_client_secret_file).is_file() or bool(
            self.settings.google_oauth_client_id and self.settings.google_oauth_client_secret
        )

    def _flow(self, state: str | None = None) -> Flow:
        options = {
            "scopes": SCOPES,
            "state": state,
            "redirect_uri": self.settings.google_oauth_redirect_uri,
            "autogenerate_code_verifier": True,
        }
        client_file = Path(self.settings.google_oauth_client_secret_file)
        if client_file.is_file():
            return Flow.from_client_secrets_file(str(client_file), **options)
        return Flow.from_client_config(
            {
                "web": {
                    "client_id": self.settings.google_oauth_client_id,
                    "client_secret": self.settings.google_oauth_client_secret.get_secret_value(),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.settings.google_oauth_redirect_uri],
                }
            },
            **options,
        )

    async def authorization_url(self, user_id: uuid.UUID) -> str:
        state = (
            base64.urlsafe_b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes)
            .decode()
            .rstrip("=")
        )
        flow = self._flow(state)
        url, _ = flow.authorization_url(
            access_type="offline", prompt="consent", include_granted_scopes="true"
        )
        if flow.code_verifier is None:
            raise DriveConfigurationError("Google OAuth did not create a PKCE verifier.")
        self.session.add(
            DriveOAuthState(
                state=state,
                user_id=user_id,
                code_verifier=flow.code_verifier,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await self.session.commit()
        return url

    async def complete_oauth(
        self, state: str, code: str, returned_scope: str | None = None
    ) -> uuid.UUID:
        oauth_state = await self.session.get(DriveOAuthState, state)
        if oauth_state is None or oauth_state.expires_at < datetime.now(UTC):
            raise DriveNotConnectedError("OAuth state is invalid or expired.")
        flow = self._flow(state)
        flow.code_verifier = oauth_state.code_verifier
        try:
            accepted = accepted_incremental_scopes(returned_scope, DRIVE_SCOPES)
        except ValueError as error:
            raise DriveNotConnectedError(str(error)) from error
        if accepted is not None:
            flow.oauth2session.scope = accepted
        await asyncio.to_thread(flow.fetch_token, code=code)
        await self._save_credentials(oauth_state.user_id, flow.credentials)
        await self.session.delete(oauth_state)
        await self.session.commit()
        return oauth_state.user_id

    async def _save_credentials(self, user_id: uuid.UUID, credentials: Credentials) -> None:
        payload = self.fernet.encrypt(credentials.to_json().encode()).decode()
        record = await self.session.get(DriveCredential, user_id)
        if record is None:
            self.session.add(DriveCredential(user_id=user_id, encrypted_payload=payload))
        else:
            record.encrypted_payload = payload

    async def _client(self, user_id: uuid.UUID):
        record = await self.session.get(DriveCredential, user_id)
        if record is None:
            raise DriveNotConnectedError(
                "Connect Google Drive through OAuth before accessing files."
            )
        raw = self.fernet.decrypt(record.encrypted_payload.encode())
        credentials = Credentials.from_authorized_user_info(json.loads(raw))
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request

            await asyncio.to_thread(credentials.refresh, Request())
            await self._save_credentials(user_id, credentials)
            await self.session.commit()
        return await execute_google_request(
            lambda: build(
                "drive",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )
        )

    async def list_files(
        self, user_id: uuid.UUID, limit: int = 100, page_token: str | None = None
    ) -> dict:
        return await self._query_files(user_id, None, limit, page_token)

    async def search_files(
        self, user_id: uuid.UUID, query: str, limit: int = 100, page_token: str | None = None
    ) -> dict:
        drive_query = self._search_query(query)
        return await self._query_files(user_id, drive_query, limit, page_token)

    async def _query_files(
        self,
        user_id: uuid.UUID,
        query: str | None,
        limit: int,
        page_token: str | None,
    ) -> dict:
        client = await self._client(user_id)
        options = {
            "pageSize": limit,
            "pageToken": page_token,
            "fields": f"nextPageToken,files({FILE_FIELDS})",
            "orderBy": "modifiedTime desc",
        }
        if query is not None:
            options["q"] = query
        response = await execute_google_request(
            lambda: client.files().list(**options).execute()
        )
        files = response.get("files", [])
        await self._sync_many(user_id, files)
        return {
            "files": [self._metadata_view(item) for item in files],
            "next_page_token": response.get("nextPageToken"),
        }

    async def get_metadata(self, user_id: uuid.UUID, file_id: str) -> dict:
        client = await self._client(user_id)
        item = await execute_google_request(
            lambda: client.files().get(fileId=file_id, fields=FILE_FIELDS).execute()
        )
        await self._sync_many(user_id, [item])
        return self._metadata_view(item)

    async def download_file(self, user_id: uuid.UUID, file_id: str) -> tuple[bytes, dict]:
        client = await self._client(user_id)
        metadata = await execute_google_request(
            lambda: client.files().get(fileId=file_id, fields=FILE_FIELDS).execute()
        )
        if metadata["mimeType"].startswith("application/vnd.google-apps."):
            if metadata["mimeType"] != GOOGLE_DOC_MIME:
                raise UnsupportedDriveFileError(
                    "This Google-native file type is not available as a binary download."
                )
            request = client.files().export_media(fileId=file_id, mimeType="text/plain")
            download_mime = "text/plain; charset=utf-8"
        else:
            request = client.files().get_media(fileId=file_id)
            download_mime = metadata["mimeType"]
        content = await execute_google_request(lambda: self._download_request(request))
        await self._sync_many(user_id, [metadata])
        return content, {**self._metadata_view(metadata), "download_mime_type": download_mime}

    async def upload_file(
        self,
        user_id: uuid.UUID,
        name: str,
        content: bytes,
        mime_type: str,
        parent_id: str | None = None,
        description: str | None = None,
    ) -> dict:
        client = await self._client(user_id)
        body = {"name": name}
        if parent_id:
            body["parents"] = [parent_id]
        if description is not None:
            body["description"] = description
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
        item = await execute_google_request(
            lambda: client.files()
            .create(body=body, media_body=media, fields=FILE_FIELDS)
            .execute()
        )
        await self._sync_many(user_id, [item])
        return self._metadata_view(item)

    async def update_metadata(
        self, user_id: uuid.UUID, file_id: str, changes: dict
    ) -> dict:
        client = await self._client(user_id)
        item = await execute_google_request(
            lambda: client.files()
            .update(fileId=file_id, body=changes, fields=FILE_FIELDS)
            .execute()
        )
        await self._sync_many(user_id, [item])
        return self._metadata_view(item)

    async def update_content(
        self, user_id: uuid.UUID, file_id: str, content: bytes, mime_type: str
    ) -> dict:
        client = await self._client(user_id)
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
        item = await execute_google_request(
            lambda: client.files()
            .update(fileId=file_id, media_body=media, fields=FILE_FIELDS)
            .execute()
        )
        await self._sync_many(user_id, [item])
        return self._metadata_view(item)

    async def delete_file(self, user_id: uuid.UUID, file_id: str) -> None:
        client = await self._client(user_id)
        await execute_google_request(
            lambda: client.files().delete(fileId=file_id).execute()
        )
        record = await self.session.get(DriveFileMetadata, (user_id, file_id))
        if record is not None:
            await self.session.delete(record)
            await self.session.commit()

    async def read_text(self, user_id: uuid.UUID, file_id: str) -> dict:
        content, metadata = await self.download_file(user_id, file_id)
        mime_type = metadata["mimeType"]
        if mime_type == GOOGLE_DOC_MIME:
            text = content.decode("utf-8", errors="replace")
        elif mime_type == PDF_MIME:
            text = self._pdf_text(content)
        elif mime_type == DOCX_MIME:
            text = self._docx_text(content)
        else:
            raise UnsupportedDriveFileError(
                "Text extraction supports Google Docs, PDF, and DOCX files."
            )
        return {"file": metadata, "text": text}

    async def _sync_many(self, user_id: uuid.UUID, files: list[dict]) -> None:
        for item in files:
            record = await self.session.get(DriveFileMetadata, (user_id, item["id"]))
            values = self._metadata_record(item)
            if record is None:
                self.session.add(
                    DriveFileMetadata(user_id=user_id, file_id=item["id"], **values)
                )
            else:
                for key, value in values.items():
                    setattr(record, key, value)
        await self.session.commit()

    @staticmethod
    def _metadata_record(item: dict) -> dict:
        modified = item.get("modifiedTime")
        return {
            "name": item.get("name", ""),
            "mime_type": item.get("mimeType", "application/octet-stream"),
            "size": int(item["size"]) if item.get("size") else None,
            "modified_time": datetime.fromisoformat(modified.replace("Z", "+00:00"))
            if modified
            else None,
            "web_view_link": item.get("webViewLink"),
            "md5_checksum": item.get("md5Checksum"),
            "parents": item.get("parents", []),
            "metadata_payload": item,
        }

    @staticmethod
    def _metadata_view(item: dict) -> dict:
        return {
            key: item[key]
            for key in (
                "id",
                "name",
                "mimeType",
                "size",
                "modifiedTime",
                "createdTime",
                "webViewLink",
                "webContentLink",
                "md5Checksum",
                "parents",
                "description",
                "trashed",
                "owners",
                "shared",
            )
            if key in item
        }

    @staticmethod
    def _search_query(query: str) -> str:
        escaped = query.replace("\\", "\\\\").replace("'", "\\'")
        return (
            f"(name contains '{escaped}' or fullText contains '{escaped}') "
            "and trashed = false"
        )

    @staticmethod
    def _download_request(request) -> bytes:
        target = io.BytesIO()
        downloader = MediaIoBaseDownload(target, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return target.getvalue()

    @staticmethod
    def _pdf_text(content: bytes) -> str:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)

    @staticmethod
    def _docx_text(content: bytes) -> str:
        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
