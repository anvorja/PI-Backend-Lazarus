"""Logs de campo subidos por los teléfonos (HU-045).

La app sube solo lo nuevo de cada archivo de evidencia (`lazarus.log`,
`notas_campo.csv`, `gps_track.csv`, `telemetry.jsonl`…). Aquí se guardan
comprimidos y el panel los une en orden para descargarlos completos.
"""

import csv
import gzip
import io
import json
import statistics
import zipfile
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Device, LogUpload
from app.services.access import utcnow

# Archivos que la app puede subir (nada más llega al servidor).
ALLOWED_FILES = {
    "lazarus.log",
    "lazarus.log.1",
    "telemetry.jsonl",
    "telemetry.jsonl.1",
    "gps_track.csv",
    "gps_track_anterior.csv",
    "notas_campo.csv",
    "notas_campo_anterior.csv",
}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def store(db: Session, device: Device, filename: str, data: bytes) -> LogUpload:
    row = LogUpload(
        device_id=device.id,
        filename=filename,
        size=len(data),
        created_at=utcnow(),
        content=gzip.compress(data),
    )
    db.add(row)
    db.commit()
    return row


def purge_old(db: Session) -> int:
    limit = utcnow() - timedelta(days=settings.log_retention_days)
    result = db.execute(delete(LogUpload).where(LogUpload.created_at < limit))
    db.commit()
    return result.rowcount or 0


def clear(db: Session, device_id: int) -> int:
    """Borra todos los fragmentos de logs del teléfono; devuelve cuántos eran."""
    result = db.execute(delete(LogUpload).where(LogUpload.device_id == device_id))
    db.commit()
    _median_cache.pop(device_id, None)
    return result.rowcount or 0


def combined(db: Session, device_id: int, names: set[str] | None = None) -> dict[str, bytes]:
    """Cada archivo completo: sus fragmentos unidos en el orden en que llegaron.
    Con [names], solo esos archivos (el registro de la app pesa varios MB)."""
    out: dict[str, list[bytes]] = {}
    query = select(LogUpload).where(LogUpload.device_id == device_id)
    if names is not None:
        query = query.where(LogUpload.filename.in_(names))
    rows = db.scalars(query.order_by(LogUpload.created_at, LogUpload.id))
    for row in rows:
        out.setdefault(row.filename, []).append(gzip.decompress(row.content))
    return {name: b"".join(parts) for name, parts in out.items()}


def as_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return buffer.getvalue()


# Mediana por dispositivo, recalculada solo cuando sube telemetría nueva.
_median_cache: dict[int, tuple[int, int | None]] = {}


def latency_median(db: Session, device_id: int) -> int | None:
    """Mediana de la latencia voz a voz (ms) del teléfono, para la lista."""
    last = db.scalar(
        select(LogUpload.id)
        .where(LogUpload.device_id == device_id, LogUpload.filename.like("telemetry%"))
        .order_by(LogUpload.id.desc())
        .limit(1)
    )
    if last is None:
        return None
    cached = _median_cache.get(device_id)
    if cached and cached[0] == last:
        return cached[1]
    rows = db.scalars(
        select(LogUpload)
        .where(LogUpload.device_id == device_id, LogUpload.filename.like("telemetry%"))
        .order_by(LogUpload.created_at, LogUpload.id)
    )
    files: dict[str, list[bytes]] = {}
    for row in rows:
        files.setdefault(row.filename, []).append(gzip.decompress(row.content))
    median = latency({k: b"".join(v) for k, v in files.items()})["median_ms"]
    _median_cache[device_id] = (last, median)
    return median


def latency(files: dict[str, bytes]) -> dict:
    """Latencia voz a voz del dispositivo, desde su telemetría subida."""
    values: list[int] = []
    for name in ("telemetry.jsonl.1", "telemetry.jsonl"):
        for line in files.get(name, b"").decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") == "latency" and event.get("kind") == "voice_to_voice":
                ms = event.get("ms")
                if isinstance(ms, int | float):
                    values.append(int(ms))
    if not values:
        return {"count": 0, "median_ms": None, "p90_ms": None}
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    return {"count": len(values), "median_ms": int(statistics.median(values)), "p90_ms": p90}


# ---- Notas y recorrido para el editor de rutas del panel ----------------------

NOTE_FILES = {"notas_campo_anterior.csv", "notas_campo.csv"}
TRACK_FILES = {"gps_track_anterior.csv", "gps_track.csv"}
# La app escribe la hora del GPS en UTC; el panel trabaja en hora de Colombia.
_BOGOTA = timedelta(hours=-5)
MAX_TRACK_POINTS = 4000


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def notes(files: dict[str, bytes]) -> list[dict]:
    """Notas de campo en orden: hora local, texto, posición y rumbo si los hay."""
    out: list[dict] = []
    for name in ("notas_campo_anterior.csv", "notas_campo.csv"):
        text = files.get(name, b"").decode("utf-8", "replace")
        for row in csv.DictReader(io.StringIO(text)):
            # Un encabezado repetido (archivo recreado) no es una nota.
            if not row.get("hora") or row.get("hora") == "hora" or not row.get("nota"):
                continue
            out.append(
                {
                    "at": row["hora"],
                    "text": row["nota"],
                    "lat": _number(row.get("latitud")),
                    "lon": _number(row.get("longitud")),
                    "accuracy_m": _number(row.get("precision_m")),
                    "reliability": row.get("estado_gps") or None,
                    "heading": _number(row.get("rumbo_grados")),
                }
            )
    return out


def track(files: dict[str, bytes], day: date | None = None) -> dict:
    """Posiciones del GPS de un día (hora de Colombia), las más recientes si no
    se dice cuál, con los días disponibles. Si son muchas, se toma una de cada N."""
    by_day: dict[date, list[dict]] = {}
    for name in ("gps_track_anterior.csv", "gps_track.csv"):
        text = files.get(name, b"").decode("utf-8", "replace")
        for cols in csv.reader(io.StringIO(text)):
            # tramo,hora,latitud,longitud,precision_m,estado,… (a veces sin encabezado)
            if len(cols) < 6:
                continue
            try:
                at = datetime.fromisoformat(cols[1].replace("Z", "+00:00"))
            except ValueError:
                continue
            lat, lon, accuracy = _number(cols[2]), _number(cols[3]), _number(cols[4])
            if lat is None or lon is None:
                continue
            local = (at + _BOGOTA).replace(tzinfo=None)
            by_day.setdefault(local.date(), []).append(
                {
                    "at": local.isoformat(timespec="seconds"),
                    "lat": lat,
                    "lon": lon,
                    "accuracy_m": accuracy,
                    "reliability": cols[5] or None,
                }
            )
    days = sorted(by_day, reverse=True)
    chosen = day if day in by_day else (days[0] if days else None)
    points = by_day.get(chosen, []) if chosen else []
    step = max(1, -(-len(points) // MAX_TRACK_POINTS))
    return {
        "days": [d.isoformat() for d in days],
        "day": chosen.isoformat() if chosen else None,
        "points": points[::step],
    }
