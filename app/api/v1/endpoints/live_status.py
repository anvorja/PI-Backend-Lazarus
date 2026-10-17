from fastapi import APIRouter, Header
from pydantic import BaseModel

from app.sockets.live_proxy import last_upstream_failure

router = APIRouter()


class LiveStatusResponse(BaseModel):
    # "paused" (en pausa), "billing" (sin saldo), "quota" (cuota agotada) o, con
    # el token del teléfono, "closed_by_admin", "device_pending",
    # "device_disabled" o "daily_limit"; None si no hay causa conocida.
    cause: str | None


@router.get(
    "/live/status",
    response_model=LiveStatusResponse,
    summary="Causa del último cierre que no se arregla reintentando",
    tags=["live"],
)
async def live_status(
    x_device_token: str | None = Header(default=None, max_length=200),
) -> LiveStatusResponse:
    return LiveStatusResponse(cause=last_upstream_failure(x_device_token))
