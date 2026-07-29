import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.session import get_db_session
from app.integrations.calendar.service import CalendarNotConnectedError, CalendarService
from app.integrations.drive.service import DriveNotConnectedError, DriveService
from app.integrations.gmail.service import GmailConfigurationError, GmailNotConnectedError, GmailService
from app.memory.embeddings import OpenAIEmbeddingProvider
from app.memory.repositories import SQLAlchemyMemoryRepository
from app.memory.search import CosineSimilaritySearchBackend
from app.memory.service import MemoryService

router = APIRouter()

class EmailRequest(BaseModel):
    to: list[str] = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1)
    cc: list[str] | None = None
    bcc: list[str] | None = None

def _service(user_id: uuid.UUID, session: AsyncSession) -> GmailService:
    memory = MemoryService(SQLAlchemyMemoryRepository(session), OpenAIEmbeddingProvider(), CosineSimilaritySearchBackend())
    return GmailService(session, memory)

async def _gmail_service(
    x_user_id: Annotated[uuid.UUID, Header()], session: Annotated[AsyncSession, Depends(get_db_session)]
) -> GmailService:
    try: return _service(x_user_id, session)
    except GmailConfigurationError as error: raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Gmail is not configured.") from error

def _error(error: GmailNotConnectedError) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, str(error))

@router.get("/oauth/authorize")
async def gmail_authorize(service: Annotated[GmailService, Depends(_gmail_service)], x_user_id: Annotated[uuid.UUID, Header()]) -> dict[str, str]:
    return {"authorization_url": await service.authorization_url(x_user_id)}

@router.get("/oauth/callback")
async def gmail_callback(
    state: str,
    code: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    scope: str | None = None,
) -> dict[str, str]:
    # The registered Google redirect is shared; persisted state selects the integration.
    try:
        service = _service(uuid.uuid4(), session)
        user_id = await service.complete_oauth(state, code, scope)
        return {"status": "connected", "integration": "gmail", "user_id": str(user_id)}
    except GmailNotConnectedError:
        try:
            user_id = await CalendarService(session).complete_oauth(state, code, scope)
            return {
                "status": "connected",
                "integration": "calendar",
                "user_id": str(user_id),
            }
        except CalendarNotConnectedError as error:
            try:
                user_id = await DriveService(session).complete_oauth(state, code, scope)
                return {
                    "status": "connected",
                    "integration": "drive",
                    "user_id": str(user_id),
                }
            except DriveNotConnectedError as drive_error:
                raise _error(GmailNotConnectedError(str(drive_error))) from drive_error

@router.get("/messages")
async def list_messages(service: Annotated[GmailService, Depends(_gmail_service)], x_user_id: Annotated[uuid.UUID, Header()], limit: int = Query(20, ge=1, le=100)):
    try: return await service.list_messages(x_user_id, limit)
    except GmailNotConnectedError as error: raise _error(error)

@router.get("/unread")
async def unread_messages(service: Annotated[GmailService, Depends(_gmail_service)], x_user_id: Annotated[uuid.UUID, Header()], limit: int = Query(20, ge=1, le=100)):
    try: return await service.get_unread_messages(x_user_id, limit)
    except GmailNotConnectedError as error: raise _error(error)

@router.get("/search")
async def search_messages(service: Annotated[GmailService, Depends(_gmail_service)], x_user_id: Annotated[uuid.UUID, Header()], query: str = Query(min_length=1), limit: int = Query(20, ge=1, le=100)):
    try: return await service.search_messages(x_user_id, query, limit)
    except GmailNotConnectedError as error: raise _error(error)

@router.post("/draft")
async def create_draft(request: EmailRequest, service: Annotated[GmailService, Depends(_gmail_service)], x_user_id: Annotated[uuid.UUID, Header()]):
    try: return await service.create_draft(x_user_id, **request.model_dump())
    except GmailNotConnectedError as error: raise _error(error)

@router.post("/send")
async def send_email(request: EmailRequest, service: Annotated[GmailService, Depends(_gmail_service)], x_user_id: Annotated[uuid.UUID, Header()]):
    try: return await service.send_email(x_user_id, **request.model_dump())
    except GmailNotConnectedError as error: raise _error(error)
