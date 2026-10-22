"""Logs de campo subidos por los teléfonos (HU-045).

La app sube solo lo nuevo de cada archivo de evidencia (`lazarus.log`,
`notas_campo.csv`, `gps_track.csv`, `telemetry.jsonl`…). Aquí se guardan
comprimidos y el panel los une en orden para descargarlos completos.
"""

import gzip
import io
import json
import statistics
import zipfile
from datetime import timedelta

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


def combined(db: Session, device_id: int) -> dict[str, bytes]:
    """Cada archivo completo: sus fragmentos unidos en el orden en que llegaron."""
    out: dict[str, list[bytes]] = {}
    rows = db.scalars(
        select(LogUpload)
        .where(LogUpload.device_id == device_id)
        .order_by(LogUpload.created_at, LogUpload.id)
    )
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
