from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.database.session import close_database_connection


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_database_connection()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Return a lightweight liveness response without querying dependencies."""
    return {"status": "ok", "environment": settings.app_env}

