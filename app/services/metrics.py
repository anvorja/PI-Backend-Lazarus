"""Métricas de capacidad del proceso: CPU, RAM, sesiones activas y tráfico del proxy.

Un muestreador (`run_sampler`) corre dentro del servidor y guarda una fila cada
`METRICS_INTERVAL_S` segundos en `metric_samples`. Se mide el proceso del backend,
no el contenedor ni la máquina, para que Render y AWS den números comparables.
"""

import asyncio
import time
from datetime import timedelta

import psutil
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import MetricSample
from app.db.session import SessionLocal
from app.services import usage
from app.services.access import utcnow

# Cada cuántos segundos se revisa el retraso del event loop dentro de un intervalo.
_TICK_S = 0.5
# Una purga de muestras viejas cada tantas muestras (a 30 s son ~cada hora).
_PURGE_EVERY = 120
# Máximo de puntos que devuelve la serie al panel.
MAX_POINTS = 500

_active_sessions = 0
_bytes_up = 0
_bytes_down = 0


def session_opened() -> None:
    global _active_sessions
    _active_sessions += 1


def session_closed() -> None:
    global _active_sessions
    _active_sessions = max(0, _active_sessions - 1)


def add_bytes(up: int = 0, down: int = 0) -> None:
    global _bytes_up, _bytes_down
    _bytes_up += up
    _bytes_down += down


def active_sessions() -> int:
    return _active_sessions


_stored_up = 0
_stored_down = 0


def pending_bytes() -> tuple[int, int]:
    """Tráfico contado que todavía no se guardó en una muestra."""
    return max(_bytes_up - _stored_up, 0), max(_bytes_down - _stored_down, 0)


def take_sample(
    process: psutil.Process, last_up: int, last_down: int, lag_s: float, interval_s: float
) -> tuple[MetricSample, int, int]:
    """Lee el proceso y arma una muestra; devuelve también los contadores de tráfico."""
    up, down = _bytes_up, _bytes_down
    sample = MetricSample(
        ts=utcnow(),
        platform=settings.platform,
        cpu_pct=round(process.cpu_percent(interval=None), 1),
        rss_mb=round(process.memory_info().rss / 1_048_576, 1),
        active_sessions=_active_sessions,
        bytes_up=up - last_up,
        bytes_down=down - last_down,
        loop_lag_ms=round(lag_s * 1000, 1),
        interval_s=round(interval_s, 1),
    )
    return sample, up, down


def _store(sample: MetricSample, purge: bool) -> None:
    global _stored_up, _stored_down
    with SessionLocal() as db:
        db.add(sample)
        # Total diario para el consumo del mes (HU-051): sobrevive a la purga.
        usage.add_day_bytes(db, sample.ts, sample.bytes_up, sample.bytes_down)
        if purge:
            limit = utcnow() - timedelta(days=settings.metrics_retention_days)
            db.execute(delete(MetricSample).where(MetricSample.ts < limit))
        db.commit()
    _stored_up += sample.bytes_up
    _stored_down += sample.bytes_down


async def run_sampler() -> None:
    """Muestrea mientras el servidor viva; un fallo de la base no detiene el proxy."""
    interval = settings.metrics_interval_s
    if interval <= 0:
        return
    process = psutil.Process()
    process.cpu_percent(interval=None)  # la primera lectura es 0 y se descarta
    last_up, last_down = _bytes_up, _bytes_down
    count = 0
    while True:
        started = time.monotonic()
        worst_lag = 0.0
        while time.monotonic() - started < interval:
            tick = time.monotonic()
            await asyncio.sleep(_TICK_S)
            worst_lag = max(worst_lag, time.monotonic() - tick - _TICK_S)
        sample, last_up, last_down = take_sample(
            process, last_up, last_down, worst_lag, time.monotonic() - started
        )
        count += 1
        try:
            await asyncio.to_thread(_store, sample, count % _PURGE_EVERY == 0)
        except Exception:  # noqa: BLE001 — las métricas no deben tumbar el servicio
            pass


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(rows: list[MetricSample]) -> dict:
    """Resumen de una plataforma: picos y costo estimado por sesión."""
    if not rows:
        return {"samples": 0}
    busy = [r for r in rows if r.active_sessions > 0]
    idle = [r for r in rows if r.active_sessions == 0]
    summary: dict = {
        "samples": len(rows),
        "cpu_avg": round(_mean([r.cpu_pct for r in rows]), 1),
        "cpu_max": max(r.cpu_pct for r in rows),
        "rss_max_mb": max(r.rss_mb for r in rows),
        "sessions_max": max(r.active_sessions for r in rows),
        "loop_lag_max_ms": max(r.loop_lag_ms for r in rows),
    }
    if busy:
        avg_sessions = _mean([r.active_sessions for r in busy])
        summary["cpu_per_session"] = round(_mean([r.cpu_pct for r in busy]) / avg_sessions, 2)
        # Ancho de banda total (ambos sentidos) entre sesiones activas.
        kbps = [
            (r.bytes_up + r.bytes_down) * 8 / 1000 / r.interval_s for r in busy if r.interval_s > 0
        ]
        summary["kbps_per_session"] = round(_mean(kbps) / avg_sessions, 1)
        if idle:
            base = _mean([r.rss_mb for r in idle])
            extra = _mean([r.rss_mb for r in busy]) - base
            summary["mb_per_session"] = round(max(extra, 0) / avg_sessions, 1)
    return summary


def series(db: Session, since, platform: str | None) -> list[MetricSample]:
    query = select(MetricSample).where(MetricSample.ts >= since).order_by(MetricSample.ts)
    if platform:
        query = query.where(MetricSample.platform == platform)
    return list(db.scalars(query))


def downsample(rows: list[MetricSample]) -> list[MetricSample]:
    """Reduce la serie a MAX_POINTS saltando muestras a intervalos regulares."""
    if len(rows) <= MAX_POINTS:
        return rows
    step = -(-len(rows) // MAX_POINTS)  # techo
    return rows[::step]
