from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Ignora variables del .env que no estén declaradas aquí, para que una
        # variable sobrante no rompa el arranque.
        extra="ignore",
    )

    # Gemini Live (audio nativo, streaming bidireccional vía proxy WebSocket).
    # Usa la Developer API (la API key viaja en query param, server-side; la
    # app nunca la ve). No requiere project id ni ADC (eso es solo Vertex).
    gemini_api_key: str = ""
    gemini_live_model: str = "gemini-2.5-flash-native-audio-latest"
    gemini_live_voice: str = "Charon"
    # Idioma por defecto si la app no lo indica en el frame `start` (es/en/fr/pt/it).
    gemini_live_language: str = "es"
    # Duración máxima de una sesión en segundos (0 = sin límite propio; solo el de
    # Gemini). Al cumplirse, la app recibe el cierre 4001 y retoma con un toque.
    # Un valor corto (p. ej. 60) sirve para probar ese flujo en el teléfono.
    gemini_live_max_session_s: float = 0
    # Interruptor del servicio: con LIVE_ENABLED=false el proxy rechaza las
    # sesiones nuevas sin abrir Gemini (no gasta saldo) y la app dice que Lazarus
    # está en pausa. Se cambia en las variables de entorno de Render.
    live_enabled: bool = True
    # Conexión directa con tokens efímeros (HU-031, ADR-0003 opción B): el
    # teléfono pide un token de un solo uso a POST /api/v1/live/token y abre la
    # sesión directo con Gemini, sin pasar el audio ni la cámara por el backend.
    # Con false el endpoint responde 404 y la app sigue usando el proxy.
    live_direct_enabled: bool = False
    # Vida del token: la sesión directa no puede durar más (la app abre otra con
    # un token nuevo). Un token sin usar vence al minuto.
    live_token_ttl_s: float = 1800
    gemini_live_direct_url: str = (
        "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage."
        "v1alpha.GenerativeService.BidiGenerateContentConstrained"
    )

    # Control de acceso por dispositivo (HU-044 a HU-046). Base de datos de
    # dispositivos, sesiones y logs de campo: Postgres en producción (Neon,
    # plan gratuito); SQLite en local y en las pruebas.
    database_url: str = "sqlite:///./lazarus.db"
    # true = solo dispositivos aprobados abren sesión. Se activa cuando todos
    # los celulares del piloto tengan la versión que se registra.
    device_auth_required: bool = False
    # Primer administrador del panel: se crea al arrancar si no hay ninguno. La
    # contraseña solo vive en las variables de entorno de Render; en la base se
    # guarda su hash Argon2.
    admin_username: str = ""
    admin_password: str = ""
    # Firma de las sesiones del panel (JWT). Sin ella, el panel no permite entrar.
    admin_jwt_secret: str = ""
    # Días que se guardan los logs subidos por los teléfonos.
    log_retention_days: int = 30
    # Muestreo de CPU, RAM y tráfico del proceso para el panel (0 = apagado).
    # PLATFORM etiqueta cada muestra ("render", "aws", "local") para compararlas.
    platform: str = "local"
    metrics_interval_s: float = 30.0
    metrics_retention_days: int = 14
    # v1alpha: necesario para `proactivity` (audio proactivo) y affective dialog.
    # v1beta rechaza el campo `proactivity` con close 1007.
    gemini_live_url: str = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"
    )

    # App
    app_name: str = "Lazarus Backend"
    app_version: str = "0.2.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str]


settings = Settings()
