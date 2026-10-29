"""Tablas del control de acceso: dispositivos, sesiones, logs de campo y panel."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# Estados de un dispositivo.
PENDING = "pending"
APPROVED = "approved"
DISABLED = "disabled"


class Device(Base):
    """Un teléfono con Lazarus. Se registra solo y queda pendiente hasta que el
    administrador lo aprueba. Del token solo se guarda el hash SHA-256."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(16), default=PENDING)
    model: Mapped[str] = mapped_column(String(80), default="")
    android: Mapped[str] = mapped_column(String(20), default="")
    app_version: Mapped[str] = mapped_column(String(40), default="")
    last_ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Minutos de sesión permitidos por día (hora de Colombia); None = sin límite.
    daily_minutes_limit: Mapped[int | None] = mapped_column(nullable=True)
    # El administrador pidió que suba sus logs en la próxima oportunidad.
    upload_requested: Mapped[bool] = mapped_column(default=False)


class DeviceSession(Base):
    """Una sesión del asistente abierta por un dispositivo."""

    __tablename__ = "device_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_s: Mapped[float] = mapped_column(default=0.0)
    close_code: Mapped[int | None] = mapped_column(nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    # Red del teléfono al abrir la sesión (la app la informa en el frame `start`).
    carrier: Mapped[str] = mapped_column(String(40), default="")
    transport: Mapped[str] = mapped_column(String(12), default="")


class LogUpload(Base):
    """Fragmento de un archivo de evidencia subido por un teléfono, comprimido
    con gzip. La app sube solo lo nuevo de cada archivo; el panel los une."""

    __tablename__ = "log_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(default=0)  # bytes sin comprimir
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))


class AdminSession(Base):
    """Refresh token del panel: solo se guarda su hash."""

    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RouteProfileRow(Base):
    """Perfil de ruta curado (HU-022) como JSON validado por
    `app.schemas.route_profile.RouteProfile`. Lleva coordenadas: vive en la base
    de datos, no en el repositorio."""

    __tablename__ = "route_profiles"

    slug: Mapped[str] = mapped_column(String(60), primary_key=True)
    data: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class AppSetting(Base):
    """Ajustes del panel (servicio abierto, horario), como JSON por clave."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class MetricSample(Base):
    """Muestra periódica del proceso del backend (CPU, RAM, sesiones, tráfico).

    Sirve para dimensionar el servidor y comparar plataformas (Render, AWS):
    `platform` viene de la variable PLATFORM del despliegue.
    """

    __tablename__ = "metric_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    cpu_pct: Mapped[float] = mapped_column(default=0.0)  # % de un núcleo
    rss_mb: Mapped[float] = mapped_column(default=0.0)
    active_sessions: Mapped[int] = mapped_column(default=0)
    bytes_up: Mapped[int] = mapped_column(default=0)  # app → Gemini en el intervalo
    bytes_down: Mapped[int] = mapped_column(default=0)  # Gemini → app en el intervalo
    loop_lag_ms: Mapped[float] = mapped_column(default=0.0)  # peor retraso del event loop
    interval_s: Mapped[float] = mapped_column(default=0.0)


class UsageDay(Base):
    """Tráfico del proxy acumulado por día de Colombia (HU-051).

    Las muestras de `metric_samples` se purgan a los 14 días; este total diario
    se conserva para comparar el mes contra el límite de transferencia de Render.
    """

    __tablename__ = "usage_days"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # AAAA-MM-DD, Colombia
    bytes_up: Mapped[int] = mapped_column(BigInteger, default=0)  # app → Gemini
    bytes_down: Mapped[int] = mapped_column(BigInteger, default=0)  # Gemini → app
