from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.atlas import AtlasAgent, AtlasConfigurationError

router = APIRouter()


class AtlasChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)


class AtlasChatResponse(BaseModel):
    reply: str


def get_atlas_agent() -> AtlasAgent:
    """Construct the agent at request time so missing secrets do not stop the API."""
    try:
        return AtlasAgent()
    except AtlasConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Atlas is unavailable because its OpenAI API key is not configured.",
        ) from error


@router.post("/chat", response_model=AtlasChatResponse)
async def chat_with_atlas(
    request: AtlasChatRequest,
    agent: Annotated[AtlasAgent, Depends(get_atlas_agent)],
) -> AtlasChatResponse:
    """Return Atlas's reply to a single user message."""
    return AtlasChatResponse(reply=await agent.chat(request.message))

