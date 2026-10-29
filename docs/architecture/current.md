# Backend — Arquitectura actual

## Resumen en una línea

FastAPI (ASGI) que hace de **proxy WebSocket** entre el cliente y la **Gemini Live API** (audio nativo). El usuario transmite audio (PCM 16 kHz) y frames de cámara (~1 fps); Gemini devuelve audio (24 kHz) en streaming, interrumpible. La API key vive solo en el backend. Estado de sesión efímero (lo gestiona la propia sesión de Gemini).

## Stack

- **Web/WS**: FastAPI 0.115+, Uvicorn (ASGI).
- **IA**: Gemini Live API — `google.ai.generativelanguage.v1alpha...BidiGenerateContent` (audio nativo, proactividad, function calling).
- **Transporte**: WebSocket nativo de FastAPI (`/ws/live`); el backend abre un segundo WebSocket (`websockets`) hacia Gemini.
- **Config**: `pydantic-settings`, `.env`.

> Sin Socket.IO, sin AWS (Rekognition/Polly), sin DeepSeek, sin OpenCV. Todo eso pertenecía al pipeline request/response anterior y se retiró.

## Estructura

```
app/
├── main.py                    # FastAPI factory → expone `app`
├── core/
│   └── config.py              # Pydantic Settings (extra="ignore")
├── prompts/
│   └── companion.py           # System prompts Live (5 idiomas) + identidad + comandos
├── services/
│   └── live_service.py        # build_upstream_url + build_setup_message + function declarations
├── sockets/
│   └── live_proxy.py          # Endpoint /ws/live: proxy bidireccional a Gemini
└── api/v1/endpoints/health.py # GET /api/v1/health
```

## Flujo de `/ws/live`

`app/sockets/live_proxy.py`

1. El cliente conecta y envía el frame `{type:"start", language, voice?, assistantName?, verbosity?, describing?}`.
2. El backend construye la URL upstream (con `GEMINI_API_KEY` en query param) y el mensaje `setup` (system prompt + voz + tools + `proactivity` + transcripción de entrada) — `live_service.py`.
3. Abre el WebSocket contra Gemini, envía `setup`, espera `setupComplete`.
4. Dos tareas asyncio (`FIRST_COMPLETED`) reenvían en ambos sentidos:
   - cliente → Gemini: `realtime_input` (audio/JPEG), `client_content` (texto/kickoff), `tool_response`.
   - Gemini → cliente: `serverContent` (audio 24 kHz, transcripciones, `interrupted`, `turnComplete`), `toolCall`.
5. Al cerrarse el upstream, propaga el motivo al cliente (close 1011).

**Modelo de interacción**: sesión continua, conversacional, interrumpible. Alertas de seguridad primero, descripciones breves, silencio cuando nada cambia.

## Personalización por voz (function calling)

Tools declaradas en `live_service._FUNCTION_DECLARATIONS` (9): `set_assistant_name`, `set_user_name`, `set_voice`, `set_language`, `set_verbosity`, `set_descriptions`, `set_system_cues`, `set_meeting_mode` (modo reunión) y `set_microphone` (silencio total). El cliente las ejecuta y persiste las de ajustes (`localStorage` en web / `LiveSettings` en Flutter); el cambio de idioma o voz reconecta la sesión. Los dos modos de silencio son de sesión (no persisten). Detalle de uso en [comandos-de-voz.md](../comandos-de-voz.md).

## Estado y persistencia

Sin estado persistente en el backend: la memoria conversacional vive en la sesión de Gemini mientras el WebSocket esté abierto. Si la conexión cae, se reinicia la sesión.

## Variables de entorno

Ver `.env.example`. Requeridas: `GEMINI_API_KEY`, `CORS_ORIGINS`. Opcionales: `GEMINI_LIVE_MODEL`, `GEMINI_LIVE_VOICE`, `DEBUG`, `HOST`, `PORT`. `config.py` usa `extra="ignore"`, así que variables sobrantes (p. ej. credenciales legacy en un `.env` antiguo) no rompen el arranque.

## Hacia dónde va (Fase 8)

El objetivo final (ver [target.md](target.md)) reduce el backend a un servicio sin estado que emite ephemeral tokens y hace de wrapper de Google Places, cuando el cliente Flutter hable directo con Gemini. Hoy seguimos en el modelo proxy.
