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
from app.services.live_service import build_setup_message, build_upstream_url

# uvicorn.error sí tiene handler configurado, así que estos logs se ven en consola.
logger = logging.getLogger("uvicorn.error")

# Espera máxima por el primer frame `start` del cliente.
START_TIMEOUT_S = 15.0


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


async def _gemini_to_client(client: WebSocket, gemini) -> None:
    """Reenvía frames de Gemini hacia la app y propaga su cierre con motivo."""
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
        code = rcvd.code if rcvd else 1011
        reason = (rcvd.reason if rcvd else "") or "upstream closed"
        if code != 1000:
            logger.warning("Live: Gemini cerró la sesión (%s) — %s", code, reason)
        # 1011 = internal error (código válido para cierre desde servidor).
        try:
            await client.close(code=1011, reason=reason[:120])
        except RuntimeError:
            pass


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

    language = start.get("language", "es")
    voice = start.get("voice")
    assistant_name = start.get("assistantName")
    user_name = start.get("userName")
    verbosity = start.get("verbosity", "concise")
    describing = start.get("describing", True)

    # 2. Abrir upstream a Gemini y enviar el setup.
    try:
        upstream_url = build_upstream_url()
    except RuntimeError as exc:
        logger.error("Live: config inválida — %s", exc)
        await client.close(code=1011, reason=str(exc)[:120])
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
            )
            await gemini.send(json.dumps(setup))
            logger.info(
                "Live: sesión Gemini iniciada (idioma=%s, voz=%s, asistente=%s, usuario=%s)",
                language,
                voice or settings.gemini_live_voice,  # voz efectiva (default si None)
                assistant_name or "Aria",
                user_name or "—",  # — = aún no ha dicho su nombre
            )

            # 3. Pipe bidireccional hasta que cualquier lado cierre.
            tasks = [
                asyncio.create_task(_client_to_gemini(client, gemini)),
                asyncio.create_task(_gemini_to_client(client, gemini)),
            ]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            # Recoge el resultado/excepción de TODAS las tareas (done + pending)
            # para no dejar excepciones "never retrieved" al cerrar la sesión.
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                    await task
    except Exception as exc:  # noqa: BLE001 — superficie de error hacia el cliente
        # Sin traceback: el mensaje de la excepción puede incluir la URL con la key.
        logger.error("Live: fallo en la sesión (%s): %s", type(exc).__name__, _redact(str(exc)))
        try:
            await client.close(code=1011, reason=_redact(f"Upstream error: {exc}")[:120])
        except RuntimeError:
            pass
        return

    try:
        await client.close()
    except RuntimeError:
        pass
    logger.info("Live: sesión finalizada")
