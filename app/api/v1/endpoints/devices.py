"""Rutas que usa la app (HU-044 y HU-045): registro, estado y logs de campo."""

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import APPROVED, Device
from app.db.session import get_db
from app.services import access, field_logs

router = APIRouter(prefix="/devices", tags=["devices"])


class RegisterRequest(BaseModel):
    model: str = Field(default="", max_length=80)
    android: str = Field(default="", max_length=20)
    app_version: str = Field(default="", max_length=40)


class RegisterResponse(BaseModel):
    # Se entrega una sola vez: el servidor solo guarda su hash.
    device_token: str
    status: str


class DeviceStatus(BaseModel):
    status: str
    name: str
    upload_requested: bool


def _ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def device_from_header(
    x_device_token: str = Header(default=""), db: Session = Depends(get_db)
) -> Device:
    if not x_device_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token del dispositivo")
    device = db.scalar(select(Device).where(Device.token_hash == access.hash_token(x_device_token)))
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Dispositivo desconocido")
    return device


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """La app se registra la primera vez y queda pendiente de aprobación."""
    token = access.new_token()
    now = access.utcnow()
    device = Device(
        token_hash=access.hash_token(token),
        model=body.model,
        android=body.android,
        app_version=body.app_version,
        last_ip=_ip(request),
        created_at=now,
        last_seen_at=now,
    )
    db.add(device)
    db.commit()
    return RegisterResponse(device_token=token, status=device.status)


@router.get("/me", response_model=DeviceStatus)
def me(
    request: Request,
    device: Device = Depends(device_from_header),
    db: Session = Depends(get_db),
    x_app_version: str = Header(default=""),
):
    if x_app_version:
        device.app_version = x_app_version[:40]
    access.touch(db, device, _ip(request), access.utcnow())
    return DeviceStatus(
        status=device.status, name=device.name, upload_requested=device.upload_requested
    )


@router.post("/me/logs", status_code=201)
async def upload_logs(
    files: list[UploadFile] = File(...),
    device: Device = Depends(device_from_header),
    db: Session = Depends(get_db),
):
    """Lo nuevo de cada archivo de evidencia, desde la última subida."""
    if device.status != APPROVED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dispositivo no aprobado")
    saved = []
    for upload in files:
        name = upload.filename or ""
        if name not in field_logs.ALLOWED_FILES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Archivo no permitido: {name}")
        data = await upload.read(field_logs.MAX_UPLOAD_BYTES + 1)
        if len(data) > field_logs.MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Archivo muy grande")
        if data:
            field_logs.store(db, device, name, data)
            saved.append(name)
    device.upload_requested = False
    db.add(device)
    db.commit()
    field_logs.purge_old(db)
    return {"saved": saved}
