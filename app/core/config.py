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
    # v1alpha: necesario para `proactivity` (audio proactivo) y affective dialog.
    # v1beta rechaza el campo `proactivity` con close 1007.
    gemini_live_url: str = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"
    )

    # App
    app_name: str = "Lazarus Backend"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str]


settings = Settings()
