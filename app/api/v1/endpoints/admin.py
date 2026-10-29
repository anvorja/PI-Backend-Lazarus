"""Rutas del panel de administración (HU-046)."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import APPROVED, DISABLED, PENDING, AdminUser, Device, DeviceSession, LogUpload
from app.db.session import get_db
from app.schemas.route_profile import RouteProfile
from app.services import access, admin_auth, field_logs, metrics, route_profiles, usage
from app.services.admin_auth import REFRESH_COOKIE, current_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ---- Sesión del administrador ----------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(max_length=60)
    password: str = Field(max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    username: str


def _set_refresh(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=int(admin_auth.REFRESH_TTL.total_seconds()),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/api/v1/admin",
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    admin = db.scalar(select(AdminUser).where(AdminUser.username == body.username))
    if admin is None or not admin_auth.verify_password(admin.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales incorrectas")
    _set_refresh(response, request, admin_auth.new_refresh(db, admin))
    return TokenResponse(access_token=admin_auth.access_token(admin), username=admin.username)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    lazarus_admin_refresh: str | None = Cookie(default=None),
):
    admin = admin_auth.use_refresh(db, lazarus_admin_refresh)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión vencida")
    _set_refresh(response, request, admin_auth.new_refresh(db, admin))
    return TokenResponse(access_token=admin_auth.access_token(admin), username=admin.username)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    lazarus_admin_refresh: str | None = Cookie(default=None),
):
    admin_auth.revoke_refresh(db, lazarus_admin_refresh)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/admin")


# ---- Ajustes: servicio abierto y horario -----------------------------------


class Schedule(BaseModel):
    enabled: bool
    days: list[int] = Field(default_factory=list)
    from_: str = Field(alias="from", pattern=r"^\d{2}:\d{2}$")
    to: str = Field(pattern=r"^\d{2}:\d{2}$")

    model_config = {"populate_by_name": True}


class UsageLimits(BaseModel):
    """Límites del mes (HU-051). 0 = sin límite definido."""

    transfer_gb: float = Field(default=100, ge=0, le=100_000)
    live_minutes: float = Field(default=0, ge=0, le=1_000_000)
    warn_pct: float = Field(default=80, ge=1, le=100)


class SettingsBody(BaseModel):
    service_open: bool | None = None
    schedule: Schedule | None = None
    usage_limits: UsageLimits | None = None


@router.get("/settings")
def get_settings(_: AdminUser = Depends(current_admin), db: Session = Depends(get_db)):
    current = access.get_settings(db)
    current["open_now"] = access.service_open(db, access.utcnow())
    return current


@router.put("/settings")
def put_settings(
    body: SettingsBody, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)
):
    values: dict = {}
    if body.service_open is not None:
        values["service_open"] = body.service_open
    if body.schedule is not None:
        values["schedule"] = body.schedule.model_dump(by_alias=True)
    if body.usage_limits is not None:
        values["usage_limits"] = body.usage_limits.model_dump()
    current = access.put_settings(db, values)
    current["open_now"] = access.service_open(db, access.utcnow())
    return current


# ---- Consumo (HU-051) ---------------------------------------------------------


@router.get("/usage")
def get_usage(_: AdminUser = Depends(current_admin), db: Session = Depends(get_db)):
    """Consumo del mes frente a los límites, y la última falla de Gemini.

    `last_failure` es 'billing' o 'quota' si una sesión reciente se cerró por
    eso (no se arregla reintentando); None si no.
    """
    from app.sockets.live_proxy import last_upstream_failure

    limits = access.get_settings(db)["usage_limits"]
    out = usage.monthly_usage(db, access.utcnow(), limits)
    cause = last_upstream_failure()
    out["last_failure"] = cause if cause in ("billing", "quota") else None
    out["limits"] = limits
    return out


@router.post("/usage/check")
async def check_usage(_: AdminUser = Depends(current_admin)):
    """Prueba ya la conexión con Gemini (sin audio): para la lista de antes de salir."""
    return await usage.check_gemini()


# ---- Dispositivos -----------------------------------------------------------


class DeviceOut(BaseModel):
    id: int
    name: str
    status: str
    model: str
    android: str
    app_version: str
    last_ip: str
    created_at: datetime
    last_seen_at: datetime | None
    daily_minutes_limit: int | None
    upload_requested: bool
    minutes_today: float
    active: bool
    uploads: int
    last_upload_at: datetime | None
    # Mediana de la latencia voz a voz (ms) de su telemetría; None sin datos.
    latency_median_ms: int | None


def _device_out(db: Session, device: Device, now: datetime) -> DeviceOut:
    uploads, last_upload = db.execute(
        select(func.count(LogUpload.id), func.max(LogUpload.created_at)).where(
            LogUpload.device_id == device.id
        )
    ).one()
    return DeviceOut(
        id=device.id,
        name=device.name,
        status=device.status,
        model=device.model,
        android=device.android,
        app_version=device.app_version,
        last_ip=device.last_ip,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        daily_minutes_limit=device.daily_minutes_limit,
        upload_requested=device.upload_requested,
        minutes_today=round(access.seconds_used_today(db, device.id, now) / 60, 1),
        active=device.id in access.active_device_ids(),
        uploads=uploads,
        last_upload_at=last_upload,
        latency_median_ms=field_logs.latency_median(db, device.id),
    )


def _device(db: Session, device_id: int) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispositivo no encontrado")
    return device


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(_: AdminUser = Depends(current_admin), db: Session = Depends(get_db)):
    now = access.utcnow()
    devices = db.scalars(select(Device).order_by(Device.created_at.desc()))
    return [_device_out(db, d, now) for d in devices]


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, pattern=f"^({PENDING}|{APPROVED}|{DISABLED})$")
    # 0 o negativo = sin límite.
    daily_minutes_limit: int | None = None
    upload_requested: bool | None = None


@router.patch("/devices/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    body: DeviceUpdate,
    _: AdminUser = Depends(current_admin),
    db: Session = Depends(get_db),
):
    device = _device(db, device_id)
    if body.name is not None:
        device.name = body.name.strip()
    if body.status is not None:
        device.status = body.status
    if body.daily_minutes_limit is not None:
        device.daily_minutes_limit = (
            body.daily_minutes_limit if body.daily_minutes_limit > 0 else None
        )
    if body.upload_requested is not None:
        device.upload_requested = body.upload_requested
    db.add(device)
    db.commit()
    # Deshabilitado: su sesión abierta se corta al instante.
    if device.status != APPROVED:
        await access.close_active(device.id)
    return _device_out(db, device, access.utcnow())


@router.post("/devices/{device_id}/close-session")
async def close_session(
    device_id: int, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)
):
    _device(db, device_id)
    return {"closed": await access.close_active(device_id)}


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: int, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)
):
    device = _device(db, device_id)
    await access.close_active(device.id)
    db.delete(device)
    db.commit()


class SessionOut(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime | None
    duration_s: float
    close_code: int | None
    ip: str
    carrier: str = ""
    transport: str = ""


@router.get("/devices/{device_id}/sessions", response_model=list[SessionOut])
def device_sessions(
    device_id: int, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)
):
    _device(db, device_id)
    rows = db.scalars(
        select(DeviceSession)
        .where(DeviceSession.device_id == device_id)
        .order_by(DeviceSession.started_at.desc())
        .limit(100)
    )
    return [
        SessionOut(
            id=r.id,
            started_at=r.started_at,
            ended_at=r.ended_at,
            duration_s=r.duration_s,
            close_code=r.close_code,
            ip=r.ip,
            carrier=r.carrier,
            transport=r.transport,
        )
        for r in rows
    ]


# ---- Logs de campo -----------------------------------------------------------


@router.get("/devices/{device_id}/logs")
def device_logs(
    device_id: int, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)
):
    """Resumen por archivo y latencia voz a voz calculada de su telemetría."""
    _device(db, device_id)
    files = field_logs.combined(db, device_id)
    return {
        "files": [{"name": n, "size": len(d)} for n, d in sorted(files.items())],
        "latency": field_logs.latency(files),
    }


@router.get("/devices/{device_id}/notes")
def device_notes(
    device_id: int, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)
):
    """Notas de campo del teléfono, para curar rutas en el panel."""
    _device(db, device_id)
    return field_logs.notes(field_logs.combined(db, device_id, field_logs.NOTE_FILES))


@router.get("/devices/{device_id}/track")
def device_track(
    device_id: int,
    day: date | None = None,
    _: AdminUser = Depends(current_admin),
    db: Session = Depends(get_db),
):
    """Recorrido GPS de un día del teléfono, para ver por dónde caminó."""
    _device(db, device_id)
    return field_logs.track(field_logs.combined(db, device_id, field_logs.TRACK_FILES), day)


@router.get("/devices/{device_id}/logs.zip")
def download_logs(
    device_id: int, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)
):
    device = _device(db, device_id)
    data = field_logs.as_zip(field_logs.combined(db, device_id))
    label = "".join(c if c.isalnum() else "-" for c in (device.name or f"dispositivo-{device.id}"))
    day = access.bogota(access.utcnow()).strftime("%Y-%m-%d")
    return RawResponse(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{label}-{day}.zip"'},
    )


@router.delete("/devices/{device_id}/logs")
def clear_logs(
    device_id: int, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)
):
    """Borra los logs subidos por el teléfono; el dispositivo y sus sesiones quedan."""
    _device(db, device_id)
    return {"deleted": field_logs.clear(db, device_id)}


# ---- Perfiles de ruta (HU-022) ----------------------------------------------


@router.get("/routes", response_model=list[RouteProfile])
def list_routes(_: AdminUser = Depends(current_admin), db: Session = Depends(get_db)):
    return route_profiles.all_profiles(db)


@router.put("/routes/{slug}", response_model=RouteProfile)
def put_route(
    slug: str,
    body: RouteProfile,
    _: AdminUser = Depends(current_admin),
    db: Session = Depends(get_db),
):
    """Crea o reemplaza un perfil. El slug de la URL y el del cuerpo coinciden."""
    if body.slug != slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El slug no coincide con la URL")
    route_profiles.save(db, body)
    return body


@router.delete("/routes/{slug}", status_code=204)
def delete_route(slug: str, _: AdminUser = Depends(current_admin), db: Session = Depends(get_db)):
    if not route_profiles.delete(db, slug):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Perfil no encontrado")


# ---- Capacidad del servidor ---------------------------------------------------


class MetricPoint(BaseModel):
    ts: datetime
    platform: str
    cpu_pct: float
    rss_mb: float
    active_sessions: int
    kbps_up: float
    kbps_down: float
    loop_lag_ms: float


@router.get("/metrics")
def get_metrics(
    hours: int = Query(default=6, ge=1, le=168),
    platform: str | None = Query(default=None, max_length=20),
    _: AdminUser = Depends(current_admin),
    db: Session = Depends(get_db),
):
    """Serie y resumen por plataforma de las muestras de las últimas `hours` horas."""
    rows = metrics.series(db, access.utcnow() - timedelta(hours=hours), platform)
    by_platform: dict[str, list] = {}
    for r in rows:
        by_platform.setdefault(r.platform, []).append(r)
    return {
        "hours": hours,
        "live_sessions": metrics.active_sessions(),
        "summary": {name: metrics.summarize(items) for name, items in by_platform.items()},
        "series": [
            MetricPoint(
                ts=r.ts,
                platform=r.platform,
                cpu_pct=r.cpu_pct,
                rss_mb=r.rss_mb,
                active_sessions=r.active_sessions,
                kbps_up=round(r.bytes_up * 8 / 1000 / r.interval_s, 1) if r.interval_s else 0,
                kbps_down=round(r.bytes_down * 8 / 1000 / r.interval_s, 1) if r.interval_s else 0,
                loop_lag_ms=r.loop_lag_ms,
            )
            for r in metrics.downsample(rows)
        ],
    }
