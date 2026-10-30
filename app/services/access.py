"""Control de acceso del piloto (HU-043 y HU-044).

Decide si un teléfono puede abrir una sesión con el asistente: servicio
abierto, horario de las jornadas de campo, dispositivo aprobado y minutos del
día. Lleva además el registro de las sesiones activas para que el panel pueda
cerrarlas.
"""

import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

from fastapi import WebSocket
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import APPROVED, DISABLED, PENDING, AppSetting, Device, DeviceSession

# Códigos de cierre hacia la app (los 4001–4005 están en el proxy).
CLOSE_PAUSED = 4006  # servicio en pausa o fuera del horario de las jornadas
CLOSE_DEVICE_PENDING = 4007  # el teléfono espera la aprobación del administrador
CLOSE_DEVICE_DISABLED = 4008  # el administrador deshabilitó el teléfono
CLOSE_DAILY_LIMIT = 4009  # se acabaron los minutos del día del teléfono
CLOSE_BY_ADMIN = 4010  # el administrador cerró la sesión desde el panel

# Colombia no tiene horario de verano: siempre UTC-5.
_BOGOTA = timedelta(hours=-5)


def utcnow() -> datetime:
    """Hora UTC sin zona (así la guardan SQLite y Postgres en estas tablas)."""
    return datetime.now(UTC).replace(tzinfo=None)


def bogota(now: datetime) -> datetime:
    return now + _BOGOTA


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---- Ajustes del panel ---------------------------------------------------

DEFAULT_SETTINGS: dict = {
    # Interruptor general del panel (además de LIVE_ENABLED en Render).
    "service_open": True,
    # Horario de las jornadas: días 0=lunes … 6=domingo, horas de Colombia.
    "schedule": {"enabled": False, "days": [5], "from": "08:00", "to": "13:00"},
    # Límites del mes para las alertas de consumo (HU-051).
    "usage_limits": {"transfer_gb": 100, "live_minutes": 0, "warn_pct": 80},
}


def get_settings(db: Session) -> dict:
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for row in db.scalars(select(AppSetting)):
        out[row.key] = json.loads(row.value)
    return out


def put_settings(db: Session, values: dict) -> dict:
    for key in DEFAULT_SETTINGS:
        if key in values:
            row = db.get(AppSetting, key) or AppSetting(key=key, value="null")
            row.value = json.dumps(values[key])
            db.add(row)
    db.commit()
    return get_settings(db)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def within_schedule(schedule: dict, now: datetime) -> bool:
    """¿La hora de Colombia de `now` (UTC) cae en el horario de las jornadas?"""
    if not schedule.get("enabled"):
        return True
    local = bogota(now)
    if local.weekday() not in schedule.get("days", []):
        return False
    minute = local.hour * 60 + local.minute
    return _minutes(schedule["from"]) <= minute < _minutes(schedule["to"])


def service_open(db: Session, now: datetime) -> bool:
    if not settings.live_enabled:
        return False
    current = get_settings(db)
    return bool(current["service_open"]) and within_schedule(current["schedule"], now)


# ---- Minutos del día ------------------------------------------------------


def _bogota_day_start(now: datetime) -> datetime:
    """Medianoche de hoy en Colombia, expresada en UTC."""
    local = bogota(now)
    return datetime(local.year, local.month, local.day) - _BOGOTA


def seconds_used_today(db: Session, device_id: int, now: datetime) -> float:
    start = _bogota_day_start(now)
    done = db.scalar(
        select(func.coalesce(func.sum(DeviceSession.duration_s), 0.0)).where(
            DeviceSession.device_id == device_id,
            DeviceSession.started_at >= start,
            DeviceSession.ended_at.is_not(None),
        )
    )
    return float(done or 0.0)


# ---- Decisión de acceso ---------------------------------------------------


def check_access(db: Session, token: str | None, now: datetime) -> tuple[Device | None, int | None]:
    """(dispositivo, código de rechazo). Sin rechazo, el código es None.

    El servicio en pausa se revisa antes que el dispositivo: así nadie gasta
    saldo fuera de las jornadas, aprobado o no.
    """
    if not service_open(db, now):
        return None, CLOSE_PAUSED
    device = None
    if token:
        device = db.scalar(select(Device).where(Device.token_hash == hash_token(token)))
    if device is None:
        if settings.device_auth_required:
            return None, CLOSE_DEVICE_PENDING
        return None, None  # versión anterior de la app, aún sin registro
    if device.status == PENDING:
        return device, CLOSE_DEVICE_PENDING
    if device.status == DISABLED:
        return device, CLOSE_DEVICE_DISABLED
    if device.daily_minutes_limit is not None:
        used = seconds_used_today(db, device.id, now)
        if used >= device.daily_minutes_limit * 60:
            return device, CLOSE_DAILY_LIMIT
    return device, None


def remaining_seconds(db: Session, device: Device, now: datetime) -> float | None:
    if device.daily_minutes_limit is None:
        return None
    return max(0.0, device.daily_minutes_limit * 60 - seconds_used_today(db, device.id, now))


def touch(db: Session, device: Device, ip: str, now: datetime) -> None:
    device.last_seen_at = now
    if ip:
        device.last_ip = ip
    db.add(device)
    db.commit()


def start_session(
    db: Session,
    device_id: int,
    ip: str,
    now: datetime,
    carrier: str = "",
    transport: str = "",
    mode: str = "",
) -> int:
    row = DeviceSession(
        device_id=device_id,
        started_at=now,
        ip=ip,
        carrier=carrier,
        transport=transport,
        mode=mode,
    )
    db.add(row)
    db.commit()
    return row.id


def end_session(db: Session, session_id: int, close_code: int | None, now: datetime) -> None:
    row = db.get(DeviceSession, session_id)
    if row is None:
        return
    row.ended_at = now
    row.duration_s = round((now - row.started_at).total_seconds(), 1)
    row.close_code = close_code
    db.add(row)
    db.commit()


def close_open_direct_sessions(db: Session, device_id: int, now: datetime) -> None:
    """Cierra las sesiones directas que la app no informó (HU-031): se cuentan
    hasta ahora, sin pasar de la vida del token."""
    rows = db.scalars(
        select(DeviceSession).where(
            DeviceSession.device_id == device_id,
            DeviceSession.mode == "direct",
            DeviceSession.ended_at.is_(None),
        )
    ).all()
    for row in rows:
        end = min(now, row.started_at + timedelta(seconds=settings.live_token_ttl_s))
        row.ended_at = end
        row.duration_s = round((end - row.started_at).total_seconds(), 1)
        db.add(row)
    if rows:
        db.commit()


# ---- Sesiones activas (para cerrarlas desde el panel) ---------------------

# Un servidor (Render, una instancia): basta con un registro en memoria.
_active: dict[int, WebSocket] = {}


def register_active(device_id: int, client: WebSocket) -> None:
    _active[device_id] = client


def unregister_active(device_id: int, client: WebSocket) -> None:
    if _active.get(device_id) is client:
        del _active[device_id]


def active_device_ids() -> set[int]:
    return set(_active)


# Sesiones cerradas desde el panel, para registrar la causa al terminar.
_admin_closed: set[int] = set()

# Cierres del panel por teléfono, para que la app sepa la causa aunque el
# código 4010 no le llegue: el 17 de octubre llegó a través de Render como un
# corte sin código y la app reconectó diciendo "Te escucho de nuevo".
_ADMIN_CLOSE_TTL_S = 120.0
_admin_closed_at: dict[int, float] = {}


def take_admin_close(device_id: int) -> bool:
    """True una sola vez si el panel cerró la sesión de este teléfono hace poco."""
    at = _admin_closed_at.pop(device_id, None)
    return at is not None and time.monotonic() - at <= _ADMIN_CLOSE_TTL_S


def closed_by_admin(device_id: int, client: WebSocket) -> bool:
    key = id(client)
    if key in _admin_closed:
        _admin_closed.discard(key)
        return True
    return False


async def close_active(device_id: int) -> bool:
    client = _active.get(device_id)
    if client is None:
        return False
    _admin_closed.add(id(client))
    _admin_closed_at[device_id] = time.monotonic()
    try:
        await client.close(code=CLOSE_BY_ADMIN, reason="closed_by_admin")
    except RuntimeError:
        pass  # ya estaba cerrada
    return True


__all__ = [
    "APPROVED",
    "CLOSE_BY_ADMIN",
    "CLOSE_DAILY_LIMIT",
    "CLOSE_DEVICE_DISABLED",
    "CLOSE_DEVICE_PENDING",
    "CLOSE_PAUSED",
    "PENDING",
]
