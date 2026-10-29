"""Consumo del piloto frente a sus límites (HU-051, LAZA-124).

El 28-oct Render suspendió el backend por agotar la transferencia del plan
gratuito (hallazgo 47), y el 29-oct las sesiones se cerraron por facturación de
Gemini. El panel muestra el consumo del mes, avisa al 80 % y puede probar la
conexión con Gemini antes de una jornada.

- **Transferencia del backend:** el proxy reenvía cada mensaje a Gemini y a la
  app, así que lo que sale del servidor es aproximadamente la suma de los dos
  sentidos. Se mide el contenido de los mensajes, sin cabeceras ni cifrado: es
  una cota inferior.
- **API de IA:** Google no permite leer el saldo de una clave de AI Studio. Se
  cuentan los minutos de Live del mes y se comparan con un presupuesto que fija
  el administrador.
"""

import asyncio
import json
from datetime import datetime

import websockets
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DeviceSession, UsageDay
from app.services import access, metrics

DEFAULT_LIMITS: dict = {
    # Transferencia mensual del plan de Render, en GB (0 = sin límite definido).
    "transfer_gb": 100,
    # Presupuesto mensual de minutos de Live (0 = sin presupuesto definido).
    "live_minutes": 0,
    # Porcentaje del límite desde el que el panel avisa.
    "warn_pct": 80,
}

_GB = 1_000_000_000


def day_key(now: datetime) -> str:
    """Día de Colombia de `now` (UTC), como AAAA-MM-DD."""
    return access.bogota(now).strftime("%Y-%m-%d")


def add_day_bytes(db: Session, now: datetime, up: int, down: int) -> None:
    """Suma el tráfico de una muestra al día de Colombia (sin hacer commit)."""
    if up <= 0 and down <= 0:
        return
    key = day_key(now)
    row = db.get(UsageDay, key) or UsageDay(day=key, bytes_up=0, bytes_down=0)
    row.bytes_up = (row.bytes_up or 0) + max(up, 0)
    row.bytes_down = (row.bytes_down or 0) + max(down, 0)
    db.add(row)


def month_start(now: datetime) -> datetime:
    """Primer día del mes de Colombia, a medianoche, expresado en UTC."""
    local = access.bogota(now)
    return datetime(local.year, local.month, 1) - (access.bogota(now) - now)


def _level(pct: float | None, warn_pct: float) -> str:
    if pct is None:
        return "unset"
    if pct >= 100:
        return "limit"
    if pct >= warn_pct:
        return "warn"
    return "ok"


def _pct(used: float, limit: float) -> float | None:
    return round(used * 100 / limit, 1) if limit > 0 else None


def monthly_usage(db: Session, now: datetime, limits: dict) -> dict:
    """Consumo del mes de Colombia en curso frente a los límites."""
    start = month_start(now)
    prefix = access.bogota(now).strftime("%Y-%m-")
    up, down = db.execute(
        select(
            func.coalesce(func.sum(UsageDay.bytes_up), 0),
            func.coalesce(func.sum(UsageDay.bytes_down), 0),
        ).where(UsageDay.day.like(prefix + "%"))
    ).one()
    # Lo de la muestra en curso todavía no está en la tabla.
    pending_up, pending_down = metrics.pending_bytes()
    up, down = int(up) + pending_up, int(down) + pending_down
    seconds, sessions = db.execute(
        select(
            func.coalesce(func.sum(DeviceSession.duration_s), 0.0),
            func.count(DeviceSession.id),
        ).where(DeviceSession.started_at >= start)
    ).one()
    warn = float(limits.get("warn_pct") or DEFAULT_LIMITS["warn_pct"])
    transfer_gb = round((up + down) / _GB, 3)
    transfer_limit = float(limits.get("transfer_gb") or 0)
    minutes = round(float(seconds) / 60, 1)
    minutes_limit = float(limits.get("live_minutes") or 0)
    transfer_pct = _pct(transfer_gb, transfer_limit)
    minutes_pct = _pct(minutes, minutes_limit)
    return {
        "month": prefix[:-1],
        "since": start,
        "warn_pct": warn,
        "transfer": {
            "used_gb": transfer_gb,
            "to_gemini_gb": round(up / _GB, 3),
            "to_app_gb": round(down / _GB, 3),
            "limit_gb": transfer_limit,
            "pct": transfer_pct,
            "level": _level(transfer_pct, warn),
        },
        "live": {
            "minutes": minutes,
            "sessions": int(sessions),
            "limit_minutes": minutes_limit,
            "pct": minutes_pct,
            "level": _level(minutes_pct, warn),
        },
    }


async def check_gemini(timeout_s: float = 15.0) -> dict:
    """Abre una sesión Live mínima con la clave del servidor y la cierra.

    Devuelve `ok`, o la causa del rechazo (`billing`, `quota`, `error`), con
    el motivo de Google sin la clave. No envía audio ni imágenes: no gasta
    minutos.
    """
    from app.services.live_service import build_upstream_url
    from app.sockets.live_proxy import (
        CLOSE_BILLING,
        CLOSE_QUOTA_EXCEEDED,
        _redact,
        _upstream_close_code,
    )

    setup = {"setup": {"model": f"models/{settings.gemini_live_model}"}}
    try:
        async with websockets.connect(build_upstream_url(), open_timeout=timeout_s) as gemini:
            await gemini.send(json.dumps(setup))
            message = await asyncio.wait_for(gemini.recv(), timeout=timeout_s)
            if isinstance(message, bytes):
                message = message.decode("utf-8", "replace")
            if "setupComplete" in message:
                return {"status": "ok", "detail": "", "model": settings.gemini_live_model}
            return {
                "status": "error",
                "detail": _redact(message)[:200],
                "model": settings.gemini_live_model,
            }
    except websockets.ConnectionClosed as exc:
        reason = exc.rcvd.reason if exc.rcvd else ""
        code = _upstream_close_code(exc.rcvd.code if exc.rcvd else 1006, reason)
        status = {CLOSE_BILLING: "billing", CLOSE_QUOTA_EXCEEDED: "quota"}.get(code, "error")
        return {
            "status": status,
            "detail": _redact(reason)[:200],
            "model": settings.gemini_live_model,
        }
    except Exception as exc:  # noqa: BLE001 — se informa al panel, no se propaga
        return {
            "status": "error",
            "detail": _redact(f"{type(exc).__name__}: {exc}")[:200],
            "model": settings.gemini_live_model,
        }
