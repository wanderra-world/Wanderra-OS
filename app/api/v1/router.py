from fastapi import APIRouter

from app.api.v1.atlas import router as atlas_router
from app.api.v1.calendar import router as calendar_router
from app.api.v1.drive import router as drive_router
from app.api.v1.gmail import router as gmail_router

router = APIRouter()
router.include_router(atlas_router, prefix="/atlas", tags=["atlas"])
router.include_router(calendar_router, prefix="/calendar", tags=["calendar"])
router.include_router(drive_router, prefix="/drive", tags=["drive"])
router.include_router(gmail_router, prefix="/gmail", tags=["gmail"])
