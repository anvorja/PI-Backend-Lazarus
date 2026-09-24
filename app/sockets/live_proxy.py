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
from urllib.parse import quote

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from app.core.config import settings
from app.prompts.companion import PROMPT_VERSION
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

_QUOTA_MARKERS = ("quota", "exhausted", "resource_exhausted", "429", "rate limit")


def _upstream_close_code(code: int, reason: str) -> int:
    """Traduce el cierre de Gemini a un código de causa para la app."""
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


async def _client_to_gemini(client: WebSocket, gemini) -> None:
    """Reenvía frames de la app hacia Gemini."""
    try:
        while True:
            message = await client.receive_text()
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


async def _gemini_to_client(client: WebSocket, gemini) -> None:
    """Reenvía frames de Gemini hacia la app y propaga su cierre con un código de causa."""
    try:
        async for message in gemini:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
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
        await _close_client(client, cause, reason)
        return
    # Gemini terminó la sesión de forma ordenada (p. ej. límite de duración).
    logger.info("Live: Gemini finalizó la sesión")
    await _close_client(client, CLOSE_UPSTREAM_ENDED, "upstream closed")


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

    language = start.get("language") or settings.gemini_live_language
    voice = start.get("voice")
    assistant_name = start.get("assistantName")
    user_name = start.get("userName")
    verbosity = start.get("verbosity", "concise")
    describing = start.get("describing", True)
    camera = start.get("camera", True)  # False: sin permiso de cámara, solo audio

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
            )
            await gemini.send(json.dumps(setup))
            logger.info(
                "Live: sesión Gemini iniciada (prompt=v%s, idioma=%s, voz=%s, asistente=%s, "
                "usuario=%s)",
                PROMPT_VERSION,
                language,
                voice or settings.gemini_live_voice,  # voz efectiva (default si None)
                assistant_name or "Aria",
                user_name or "—",  # — = aún no ha dicho su nombre
            )

            # 3. Pipe bidireccional hasta que cualquier lado cierre.
            limit = asyncio.create_task(_session_limit(settings.gemini_live_max_session_s))
            tasks = [
                asyncio.create_task(_client_to_gemini(client, gemini)),
                asyncio.create_task(_gemini_to_client(client, gemini)),
                limit,
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            # Recoge el resultado/excepción de TODAS las tareas (done + pending)
            # para no dejar excepciones "never retrieved" al cerrar la sesión.
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                    await task
            if limit in done:
                # Mismo aviso que cuando Gemini termina la sesión por su cuenta.
                logger.info("Live: se cumplió la duración máxima de la sesión")
                await gemini.close()
                await _close_client(client, CLOSE_UPSTREAM_ENDED, "session time limit")
                return
    except Exception as exc:  # noqa: BLE001 — superficie de error hacia el cliente
        # Sin traceback: el mensaje de la excepción puede incluir la URL con la key.
        text = _redact(str(exc))
        cause = _upstream_close_code(1011, text)
        logger.error("Live: fallo en la sesión (%s → %s): %s", type(exc).__name__, cause, text)
        await _close_client(client, cause, f"Upstream error: {text}")
        return

    try:
        await client.close()
    except RuntimeError:
        pass
    logger.info("Live: sesión finalizada")
