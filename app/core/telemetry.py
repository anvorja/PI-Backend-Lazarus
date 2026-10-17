"""Eventos estructurados de sesión (HU-015): una línea JSON por evento.

Solo metadatos: identificador corto de sesión, versión del prompt, idioma, voz,
códigos de cierre, duraciones y conteos de mensajes. Nunca audio, imágenes,
transcripciones, el nombre de la persona ni la API key.
"""

import json
import logging
import time
import uuid

telemetry_logger = logging.getLogger("lazarus.telemetry")


def configure_telemetry_logging() -> None:
    """Escribe los eventos en la consola, una línea JSON sin prefijos."""
    if telemetry_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    telemetry_logger.addHandler(handler)
    telemetry_logger.setLevel(logging.INFO)
    telemetry_logger.propagate = False


def new_session_id() -> str:
    return uuid.uuid4().hex[:8]


def session_event(event: str, session: str, **fields: object) -> None:
    payload = {"ts": round(time.time(), 3), "event": event, "session": session, **fields}
    telemetry_logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
