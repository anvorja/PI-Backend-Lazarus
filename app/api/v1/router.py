from fastapi import APIRouter

from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.live_status import router as live_status_router

router = APIRouter(prefix="/api/v1")

router.include_router(health_router)
router.include_router(live_status_router)
