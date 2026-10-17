from fastapi import APIRouter
from pydantic import BaseModel

from app.sockets.live_proxy import last_upstream_failure

router = APIRouter()


class LiveStatusResponse(BaseModel):
    # "billing" (sin saldo), "quota" (cuota agotada) o None.
    cause: str | None


@router.get(
    "/live/status",
    response_model=LiveStatusResponse,
    summary="Causa de la última falla de Gemini que no se arregla reintentando",
    tags=["live"],
)
async def live_status() -> LiveStatusResponse:
    return LiveStatusResponse(cause=last_upstream_failure())
