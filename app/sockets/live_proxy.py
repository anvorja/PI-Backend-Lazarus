"""Proxy WebSocket entre la app móvil y la Gemini Live API.

Flujo:
    [app móvil] --ws--> /ws/live (este proxy) --ws--> Gemini Live API

- La app envía como primer frame `{"type": "start", "language": "es",
  "voice": "Charon"}`. Con eso el backend arma el `setup` (system prompt
  server-side) y lo manda a Gemini.
- A partir de ahí el proxy reenvía todo de forma transparente en ambos sentidos:
  audio/imagen/texto del cliente -> Gemini, y audio nativo/transcripciones/
  tool-calls de Gemini -> cliente.

La API key nunca llega al dispositivo: el proxy abre la conexión upstream con la
key tomada de `.env` (ver `live_service.build_upstream_url`).
"""

import asyncio
import contextlib
import json
import logging
import time
from urllib.parse import quote

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from app.core.config import settings
from app.core.telemetry import new_session_id, session_event
from app.db.session import SessionLocal
from app.prompts.companion import PROMPT_VERSION
from app.services import access, metrics
from app.services.access import CLOSE_DAILY_LIMIT, CLOSE_PAUSED
from app.services.live_service import build_setup_message, build_upstream_url

# uvicorn.error sí tiene handler configurado, así que estos logs se ven en consola.
logger = logging.getLogger("uvicorn.error")

# Espera máxima por el primer frame `start` del cliente.
START_TIMEOUT_S = 15.0

# Códigos de cierre hacia la app (rango 4000-4999, reservado para la aplicación).
# La app decide con ellos si reconecta sola o avisa a la persona.
CLOSE_UPSTREAM_ENDED = 4001  # Gemini cerró la sesión (p. ej. límite de duración)
CLOSE_UPSTREAM_ERROR = 4002  # fallo de red o de protocolo con Gemini
CLOSE_QUOTA_EXCEEDED = 4003  # cuota de la API agotada
CLOSE_MISCONFIGURED = 4004  # el servidor no tiene API key
CLOSE_BILLING = 4005  # sin saldo o facturación del proyecto (no se resuelve esperando)
# 4006–4010: control de acceso (servicio en pausa, dispositivo y panel).

_QUOTA_MARKERS = ("quota", "exhausted", "resource_exhausted", "429", "rate limit")
# Antes que la cuota: "credits are depleted" no se arregla reintentando más tarde;
# alguien tiene que recargar el saldo (visto en la prueba de CP-LAZA-39).
# "Spending cap": el proyecto llegó a su tope de gasto mensual (visto el 6 de
# octubre); también se arregla solo desde AI Studio.
_BILLING_MARKERS = (
    "credits",
    "billing",
    "prepayment",
    "payment",
    "depleted",
    "spending cap",
)


def _upstream_close_code(code: int, reason: str) -> int:
    """Traduce el cierre de Gemini a un código de causa para la app."""
    if any(marker in reason.lower() for marker in _BILLING_MARKERS):
        return CLOSE_BILLING
    if any(marker in reason.lower() for marker in _QUOTA_MARKERS):
        return CLOSE_QUOTA_EXCEEDED
    if code in (1000, 1001):
        return CLOSE_UPSTREAM_ENDED
    return CLOSE_UPSTREAM_ERROR


def _redact(text: str) -> str:
    """Oculta la API key si aparece en un texto (p. ej. la URL dentro de un error)."""
    key = settings.gemini_api_key
    if not key:
        return text
    return text.replace(quote(key), "***").replace(key, "***")


async def _client_to_gemini(client: WebSocket, gemini, stats: dict | None = None) -> None:
    """Reenvía frames de la app hacia Gemini."""
    try:
        while True:
            message = await client.receive_text()
            if stats is not None:
                stats["from_app"] += 1
            metrics.add_bytes(up=len(message))
            await gemini.send(message)
    except WebSocketDisconnect:
        logger.info("Live: cliente desconectado")
        await gemini.close()
    except ConnectionClosed:
        pass


async def _session_limit(seconds: float) -> None:
    """Termina cuando se cumple la duración máxima de la sesión (nunca si es 0)."""
    if seconds <= 0:
        await asyncio.Event().wait()
    await asyncio.sleep(seconds)


async def _close_client(client: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(RuntimeError):
        await client.close(code=code, reason=_redact(reason)[:120])


async def _gemini_to_client(client: WebSocket, gemini, stats: dict | None = None) -> None:
    """Reenvía frames de Gemini hacia la app y propaga su cierre con un código de causa."""
    try:
        async for message in gemini:
            if stats is not None:
                stats["from_gemini"] += 1
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            metrics.add_bytes(down=len(message))
            try:
                await client.send_text(message)
            except (WebSocketDisconnect, RuntimeError):
                # El cliente ya cerró (p. ej. reconexión por cambio de idioma);
                # dejamos de reenviar sin ruido. RuntimeError = envío tras close.
                return
    except ConnectionClosed as exc:
        rcvd = exc.rcvd
        code = rcvd.code if rcvd else 1006
        reason = (rcvd.reason if rcvd else "") or "upstream closed"
        cause = _upstream_close_code(code, reason)
        logger.warning("Live: Gemini cerró la sesión (%s → %s) — %s", code, cause, reason)
        if stats is not None:
            stats["close_code"] = cause
        await _close_client(client, cause, reason)
        return
    # Gemini terminó la sesión de forma ordenada (p. ej. límite de duración).
    logger.info("Live: Gemini finalizó la sesión")
    if stats is not None:
        stats["close_code"] = CLOSE_UPSTREAM_ENDED
    await _close_client(client, CLOSE_UPSTREAM_ENDED, "upstream closed")


# Última falla de Gemini que no se arregla reintentando (sin saldo o sin cuota).
# En la Fase 0 (17 de octubre), con el saldo agotado, el cierre llegó a la app
# sin código a través de Render y la app solo dijo "no se pudo conectar". La app
# consulta esta causa en GET /api/v1/live/status cuando la conexión se corta sin
# código.
_FAILURE_TTL_S = 600.0
_last_failure: tuple[int, float] | None = None


_DEVICE_CAUSES = {
    access.CLOSE_PAUSED: "paused",
    access.CLOSE_DEVICE_PENDING: "device_pending",
    access.CLOSE_DEVICE_DISABLED: "device_disabled",
    access.CLOSE_DAILY_LIMIT: "daily_limit",
}


def last_upstream_failure(device_token: str | None = None) -> str | None:
    """'paused' si el servicio está en pausa; con el token del teléfono, además
    'closed_by_admin', 'device_pending', 'device_disabled' o 'daily_limit';
    'billing' o 'quota' si la última sesión terminó así hace poco; si no, None."""
    if not settings.live_enabled:
        return "paused"
    try:
        with SessionLocal() as db:
            now = access.utcnow()
            if not access.service_open(db, now):
                return "paused"
            if device_token:
                device, refuse = access.check_access(db, device_token, now)
                if device is not None and access.take_admin_close(device.id):
                    return "closed_by_admin"
                if refuse is not None:
                    return _DEVICE_CAUSES.get(refuse)
    except Exception:  # noqa: BLE001 — sin base, solo cuenta LIVE_ENABLED
        pass
    if _last_failure is None:
        return None
    code, at = _last_failure
    if time.monotonic() - at > _FAILURE_TTL_S:
        return None
    return {CLOSE_BILLING: "billing", CLOSE_QUOTA_EXCEEDED: "quota"}.get(code)


def _remember_outcome(stats: dict) -> None:
    global _last_failure
    code = stats.get("close_code")
    if code in (CLOSE_BILLING, CLOSE_QUOTA_EXCEEDED):
        _last_failure = (code, time.monotonic())
    elif stats.get("from_gemini"):
        _last_failure = None  # Gemini respondió: ya no hay falla vigente


def _end(session_id: str, started: float, stats: dict) -> None:
    """Evento de fin de sesión con su duración, cierre y conteo de mensajes."""
    _remember_outcome(stats)
    session_event(
        "session_end",
        session_id,
        duration_s=round(time.monotonic() - started, 1),
        **stats,
    )


async def live_proxy(client: WebSocket) -> None:
    """Endpoint WebSocket `/ws/live`."""
    await client.accept()
    logger.info("Live: nueva sesión")

    # 1. Esperar el frame `start` del cliente (idioma / voz).
    try:
        raw = await asyncio.wait_for(client.receive_text(), timeout=START_TIMEOUT_S)
        start = json.loads(raw)
    except TimeoutError:
        await client.close(code=1008, reason="No se recibió el frame 'start'")
        return
    except (WebSocketDisconnect, json.JSONDecodeError):
        await client.close(code=1008, reason="Frame 'start' inválido")
        return

    if start.get("type") != "start":
        await client.close(code=1008, reason="Se esperaba {type:'start'}")
        return

    # Servicio en pausa: se rechaza antes de abrir Gemini, sin gastar saldo.
    if not settings.live_enabled:
        logger.info("Live: servicio en pausa (LIVE_ENABLED=false), sesión rechazada")
        await client.close(code=CLOSE_PAUSED, reason="paused")
        return

    # Control de acceso (HU-044): horario, dispositivo aprobado y minutos del día.
    ip = _client_ip(client)
    try:
        granted = await asyncio.to_thread(
            _grant, start.get("deviceToken"), ip, *parse_network(start.get("network"))
        )
    except Exception as exc:  # noqa: BLE001 — sin base no se bloquea el piloto
        logger.error("Live: control de acceso no disponible (%s)", type(exc).__name__)
        granted = (None, None, None, None)
    device_id, refuse, record_id, remaining = granted
    if refuse is not None:
        logger.info("Live: sesión rechazada por el control de acceso (%s)", refuse)
        await client.close(code=refuse, reason=_REFUSE_REASONS.get(refuse, "refused"))
        return
    if device_id is not None:
        access.register_active(device_id, client)
    stats: dict = {"from_app": 0, "from_gemini": 0, "close_code": None}
    metrics.session_opened()
    try:
        await _run_session(client, start, stats, remaining)
    finally:
        metrics.session_closed()
        if device_id is not None:
            access.unregister_active(device_id, client)
            code = stats.get("close_code")
            if access.closed_by_admin(device_id, client):
                code = access.CLOSE_BY_ADMIN
            # Síncrono: si la tarea se cancela al cerrar, un await aquí se
            # cancelaría también y la sesión quedaría sin cierre ni duración.
            with contextlib.suppress(Exception):
                _finish(record_id, code)


_REFUSE_REASONS = {
    access.CLOSE_PAUSED: "paused",
    access.CLOSE_DEVICE_PENDING: "device_pending",
    access.CLOSE_DEVICE_DISABLED: "device_disabled",
    access.CLOSE_DAILY_LIMIT: "daily_limit",
}


_TRANSPORTS = {"wifi", "cellular", "other", "none"}


def parse_network(raw: object) -> tuple[str, str]:
    """(operador, tipo de red) del frame `start`; vacíos si faltan o no son válidos.

    El operador es texto libre del teléfono (p. ej. "Claro"): se recorta y se
    limpia de caracteres de control antes de guardarlo.
    """
    if not isinstance(raw, dict):
        return "", ""
    carrier = raw.get("operator")
    transport = raw.get("transport")
    carrier = (
        "".join(c for c in carrier if c.isprintable()).strip()[:40]
        if isinstance(carrier, str)
        else ""
    )
    transport = transport if isinstance(transport, str) and transport in _TRANSPORTS else ""
    return carrier, transport


def _client_ip(client: WebSocket) -> str:
    # Render pone la IP real en X-Forwarded-For.
    forwarded = client.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (client.client.host if client.client else "")[:64]


def _grant(token: str | None, ip: str, carrier: str = "", transport: str = ""):
    """(device_id, código de rechazo, id del registro de sesión, segundos restantes)."""
    now = access.utcnow()
    with SessionLocal() as db:
        device, refuse = access.check_access(db, token, now)
        if device is not None:
            access.touch(db, device, ip, now)
        if refuse is not None or device is None:
            return (device.id if device else None, refuse, None, None)
        remaining = access.remaining_seconds(db, device, now)
        record = access.start_session(db, device.id, ip, now, carrier, transport)
        return (device.id, None, record, remaining)


def _finish(record_id: int | None, code: int | None) -> None:
    if record_id is None:
        return
    with SessionLocal() as db:
        access.end_session(db, record_id, code, access.utcnow())


async def _run_session(
    client: WebSocket, start: dict, stats: dict, remaining: float | None
) -> None:
    """Abre Gemini y reenvía en ambos sentidos hasta que alguien cierre."""
    language = start.get("language") or settings.gemini_live_language
    voice = start.get("voice")
    assistant_name = start.get("assistantName")
    user_name = start.get("userName")
    verbosity = start.get("verbosity", "concise")
    describing = start.get("describing", True)
    camera = start.get("camera", True)  # False: sin permiso de cámara, solo audio
    # True: sesión abierta con la pantalla bloqueada, sin imágenes (HU-017).
    screen_locked = start.get("screenLocked", False)
    # True: la persona usa TalkBack; los gestos se indican como "toca dos veces" (HU-023).
    screen_reader = start.get("screenReader", False)

    session_id = new_session_id()
    started = time.monotonic()

    # 2. Abrir upstream a Gemini y enviar el setup.
    try:
        upstream_url = build_upstream_url()
    except RuntimeError as exc:
        logger.error("Live: config inválida — %s", exc)
        await client.close(code=CLOSE_MISCONFIGURED, reason=str(exc)[:120])
        return

    try:
        async with websockets.connect(upstream_url) as gemini:
            setup = build_setup_message(
                language,
                voice,
                assistant_name,
                user_name=user_name,
                verbosity=verbosity,
                describing=describing,
                camera=camera,
                screen_locked=bool(screen_locked),
                screen_reader=bool(screen_reader),
            )
            await gemini.send(json.dumps(setup))
            logger.info(
                "Live: sesión Gemini iniciada (prompt=v%s, idioma=%s, voz=%s, asistente=%s, "
                "nombre de la persona: %s)",
                PROMPT_VERSION,
                language,
                voice or settings.gemini_live_voice,  # voz efectiva (default si None)
                assistant_name or "Aria",
                "conocido" if user_name else "—",  # el nombre no va al log (privacidad)
            )
            carrier, transport = parse_network(start.get("network"))
            session_event(
                "session_start",
                session_id,
                carrier=carrier,
                transport=transport,
                prompt=PROMPT_VERSION,
                language=language,
                voice=voice or settings.gemini_live_voice,
                describing=bool(describing),
                camera=bool(camera),
                screen_locked=bool(screen_locked),
                screen_reader=bool(screen_reader),
                user_name_known=bool(user_name),
            )

            # 3. Pipe bidireccional hasta que cualquier lado cierre.
            limit = asyncio.create_task(_session_limit(settings.gemini_live_max_session_s))
            # Minutos del día del teléfono (HU-044): al acabarse, se cierra.
            daily = asyncio.create_task(_session_limit(remaining if remaining is not None else 0))
            tasks = [
                asyncio.create_task(_client_to_gemini(client, gemini, stats)),
                asyncio.create_task(_gemini_to_client(client, gemini, stats)),
                limit,
                daily,
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            # Recoge el resultado/excepción de TODAS las tareas (done + pending)
            # para no dejar excepciones "never retrieved" al cerrar la sesión.
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                    await task
            if daily in done:
                logger.info("Live: se acabaron los minutos del día del dispositivo")
                stats["close_code"] = CLOSE_DAILY_LIMIT
                _end(session_id, started, stats)
                await gemini.close()
                await _close_client(client, CLOSE_DAILY_LIMIT, "daily_limit")
                return
            if limit in done:
                # Mismo aviso que cuando Gemini termina la sesión por su cuenta.
                logger.info("Live: se cumplió la duración máxima de la sesión")
                stats["close_code"] = CLOSE_UPSTREAM_ENDED
                _end(session_id, started, stats)
                await gemini.close()
                await _close_client(client, CLOSE_UPSTREAM_ENDED, "session time limit")
                return
    except Exception as exc:  # noqa: BLE001 — superficie de error hacia el cliente
        # Sin traceback: el mensaje de la excepción puede incluir la URL con la key.
        text = _redact(str(exc))
        cause = _upstream_close_code(1011, text)
        logger.error("Live: fallo en la sesión (%s → %s): %s", type(exc).__name__, cause, text)
        stats["close_code"] = cause
        stats["error"] = type(exc).__name__
        _end(session_id, started, stats)
        await _close_client(client, cause, f"Upstream error: {text}")
        return

    _end(session_id, started, stats)
    try:
        await client.close()
    except RuntimeError:
        pass
    logger.info("Live: sesión finalizada")
