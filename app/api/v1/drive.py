import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.integrations.drive.service import (
    DriveConfigurationError,
    DriveNotConnectedError,
    DriveService,
    UnsupportedDriveFileError,
)
from app.integrations.errors import ProviderOperationError

router = APIRouter()


class UpdateFileRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=1024)
    description: str | None = None
    starred: bool | None = None

    @model_validator(mode="after")
    def at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        return self


def _service(session: AsyncSession) -> DriveService:
    return DriveService(session)


async def _drive_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DriveService:
    try:
        return _service(session)
    except DriveConfigurationError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Google Drive is not configured."
        ) from error


def _raise_integration_error(error: Exception) -> None:
    if isinstance(error, DriveNotConnectedError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    if isinstance(error, UnsupportedDriveFileError):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(error)) from error
    if isinstance(error, ProviderOperationError):
        raise HTTPException(error.status_code, str(error)) from error
    raise error


@router.get("/oauth/authorize")
async def drive_authorize(
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
) -> dict[str, str]:
    return {"authorization_url": await service.authorization_url(x_user_id)}


@router.get("/files")
async def list_files(
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
    limit: int = Query(100, ge=1, le=1000),
    page_token: str | None = None,
):
    try:
        return await service.list_files(x_user_id, limit, page_token)
    except (DriveNotConnectedError, ProviderOperationError) as error:
        _raise_integration_error(error)


@router.get("/search")
async def search_files(
    query: str,
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
    limit: int = Query(100, ge=1, le=1000),
    page_token: str | None = None,
):
    try:
        return await service.search_files(x_user_id, query, limit, page_token)
    except (DriveNotConnectedError, ProviderOperationError) as error:
        _raise_integration_error(error)


@router.get("/files/{file_id}/metadata")
async def read_metadata(
    file_id: str,
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
):
    try:
        return await service.get_metadata(x_user_id, file_id)
    except (DriveNotConnectedError, ProviderOperationError) as error:
        _raise_integration_error(error)


@router.get("/files/{file_id}/content")
async def download_file(
    file_id: str,
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
) -> Response:
    try:
        content, metadata = await service.download_file(x_user_id, file_id)
        filename = quote(metadata.get("name", "download"))
        return Response(
            content=content,
            media_type=metadata["download_mime_type"],
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )
    except (
        DriveNotConnectedError,
        UnsupportedDriveFileError,
        ProviderOperationError,
    ) as error:
        _raise_integration_error(error)


@router.get("/files/{file_id}/text")
async def read_file_text(
    file_id: str,
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
):
    try:
        return await service.read_text(x_user_id, file_id)
    except (
        DriveNotConnectedError,
        UnsupportedDriveFileError,
        ProviderOperationError,
    ) as error:
        _raise_integration_error(error)


@router.post("/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
    file: UploadFile = File(),
    parent_id: str | None = Form(None),
    description: str | None = Form(None),
):
    try:
        content = await file.read()
        return await service.upload_file(
            x_user_id,
            file.filename or "upload",
            content,
            file.content_type or "application/octet-stream",
            parent_id,
            description,
        )
    except (DriveNotConnectedError, ProviderOperationError) as error:
        _raise_integration_error(error)


@router.patch("/files/{file_id}")
async def update_file_metadata(
    file_id: str,
    request: UpdateFileRequest,
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
):
    try:
        changes = request.model_dump(exclude_none=True)
        return await service.update_metadata(x_user_id, file_id, changes)
    except (DriveNotConnectedError, ProviderOperationError) as error:
        _raise_integration_error(error)


@router.put("/files/{file_id}/content")
async def update_file_content(
    file_id: str,
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
    file: UploadFile = File(),
):
    try:
        return await service.update_content(
            x_user_id,
            file_id,
            await file.read(),
            file.content_type or "application/octet-stream",
        )
    except (DriveNotConnectedError, ProviderOperationError) as error:
        _raise_integration_error(error)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    service: Annotated[DriveService, Depends(_drive_service)],
    x_user_id: Annotated[uuid.UUID, Header()],
) -> Response:
    try:
        await service.delete_file(x_user_id, file_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except (DriveNotConnectedError, ProviderOperationError) as error:
        _raise_integration_error(error)
