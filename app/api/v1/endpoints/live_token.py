"""Sesión directa con Gemini Live mediante un token efímero (HU-031).

`POST /live/token` aplica las mismas reglas del piloto que el proxy `/ws/live`
(servicio abierto, teléfono aprobado, horario y minutos del día) y entrega un
token de un solo uso con el system prompt fijado. `POST /live/sessions/{id}/end`
lo llama la app al terminar, para contar los minutos como con el proxy.
"""

import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.telemetry import new_session_id, session_event
from app.db.models import Device, DeviceSession
from app.db.session import SessionLocal
from app.prompts.companion import PROMPT_VERSION
from app.services import access, live_token
from app.services.live_service import build_setup_message
from app.sockets import live_proxy

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class LiveTokenRequest(BaseModel):
    """Los mismos datos que el frame `start` del proxy."""

    model_config = ConfigDict(populate_by_name=True)

    language: str | None = Field(default=None, max_length=8)
    voice: str | None = Field(default=None, max_length=40)
    assistant_name: str | None = Field(default=None, alias="assistantName", max_length=40)
    user_name: str | None = Field(default=None, alias="userName", max_length=60)
    verbosity: str = Field(default="concise", max_length=12)
    describing: bool = True
    camera: bool = True
    screen_locked: bool = Field(default=False, alias="screenLocked")
    screen_reader: bool = Field(default=False, alias="screenReader")
    network: dict | None = None


class LiveTokenResponse(BaseModel):
    token: str
    url: str
    model: str
    session_id: int | None
    expires_in_s: float


def _refuse(code: int) -> JSONResponse:
    # La app trata el código como el cierre equivalente del proxy.
    reason = live_proxy._REFUSE_REASONS.get(code, "refused")
    return JSONResponse(status_code=403, content={"code": code, "reason": reason})


@router.post(
    "/live/token",
    response_model=LiveTokenResponse,
    summary="Token efímero para abrir la sesión directo con Gemini Live",
    tags=["live"],
)
async def issue_live_token(
    body: LiveTokenRequest,
    request: Request,
    x_device_token: str | None = Header(default=None, max_length=200),
):
    if not settings.live_direct_enabled:
        raise HTTPException(status_code=404, detail="direct_disabled")
    if not settings.live_enabled:
        return _refuse(access.CLOSE_PAUSED)

    forwarded = request.headers.get("x-forwarded-for", "")
    ip = (forwarded.split(",")[0].strip() if forwarded else (request.client.host or ""))[:64]
    carrier, transport = live_proxy.parse_network(body.network)

    def grant():
        now = access.utcnow()
        with SessionLocal() as db:
            device, refuse = access.check_access(db, x_device_token, now)
            if device is not None:
                access.touch(db, device, ip, now)
            if refuse is not None:
                return refuse, None, None
            if device is None:
                return None, None, None  # sin registro y sin exigirlo (como el proxy)
            access.close_open_direct_sessions(db, device.id, now)
            remaining = access.remaining_seconds(db, device, now)
            record = access.start_session(db, device.id, ip, now, carrier, transport, "direct")
            return None, record, remaining

    refuse, record_id, remaining = await asyncio.to_thread(grant)
    if refuse is not None:
        logger.info("Live: token rechazado por el control de acceso (%s)", refuse)
        return _refuse(refuse)

    ttl = settings.live_token_ttl_s
    if settings.gemini_live_max_session_s:
        ttl = min(ttl, settings.gemini_live_max_session_s)
    if remaining is not None:
        ttl = min(ttl, remaining)

    language = body.language or settings.gemini_live_language
    setup = build_setup_message(
        language,
        body.voice,
        body.assistant_name,
        user_name=body.user_name,
        verbosity=body.verbosity,
        describing=body.describing,
        camera=body.camera,
        screen_locked=body.screen_locked,
        screen_reader=body.screen_reader,
    )
    try:
        token = await asyncio.to_thread(live_token.create_token, setup, ttl)
    except Exception as exc:  # noqa: BLE001 — la app cae al proxy, que da la causa
        logger.error("Live: no se pudo emitir el token (%s)", type(exc).__name__)
        if record_id is not None:
            await asyncio.to_thread(_end_record, record_id, live_proxy.CLOSE_UPSTREAM_ERROR)
        raise HTTPException(status_code=502, detail="token_unavailable") from None

    logger.info(
        "Live: token efímero emitido (prompt=v%s, idioma=%s, vida=%.0f s)",
        PROMPT_VERSION,
        language,
        ttl,
    )
    session_event(
        "session_start",
        new_session_id(),
        carrier=carrier,
        transport=transport,
        prompt=PROMPT_VERSION,
        language=language,
        voice=body.voice or settings.gemini_live_voice,
        direct=True,
    )
    return LiveTokenResponse(
        token=token,
        url=settings.gemini_live_direct_url,
        model=f"models/{settings.gemini_live_model}",
        session_id=record_id,
        expires_in_s=ttl,
    )


class LiveSessionEnd(BaseModel):
    close_code: int | None = Field(default=None, alias="closeCode")


def _end_record(record_id: int, code: int | None) -> None:
    with SessionLocal() as db:
        access.end_session(db, record_id, code, access.utcnow())


@router.post(
    "/live/sessions/{session_id}/end",
    status_code=204,
    summary="La app informa el fin de una sesión directa",
    tags=["live"],
)
async def end_live_session(
    session_id: int,
    body: LiveSessionEnd,
    x_device_token: str | None = Header(default=None, max_length=200),
) -> Response:
    def end() -> bool:
        now = access.utcnow()
        with SessionLocal() as db:
            # Por el token y no por check_access: con el servicio en pausa o los
            # minutos agotados la sesión igual se cierra.
            device = (
                db.scalar(
                    select(Device).where(Device.token_hash == access.hash_token(x_device_token))
                )
                if x_device_token
                else None
            )
            row = db.get(DeviceSession, session_id)
            if device is None or row is None or row.device_id != device.id:
                return False
            if row.ended_at is None:
                access.end_session(db, session_id, body.close_code, now)
            return True

    if not await asyncio.to_thread(end):
        raise HTTPException(status_code=404, detail="session_not_found")
    # Sin saldo o sin cuota: GET /live/status lo informa igual que con el proxy.
    live_proxy._remember_outcome({"close_code": body.close_code})
    return Response(status_code=204)
