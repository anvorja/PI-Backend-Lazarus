# Lazarus — Backend

Backend de **Lazarus**, copiloto conversacional de movilidad asistida para personas con
discapacidad visual. Actúa como **proxy WebSocket seguro** entre la app móvil y la
**Gemini Live API**: la API key de Gemini vive solo en el servidor y nunca llega al
teléfono.

Proyecto gestionado en Jira (proyecto **LAZA**). Cada cambio entra por una rama
`feature/LAZA-<n>-…` y un Pull Request hacia `develop`.

## Stack

| Capa | Tecnología |
| --- | --- |
| Framework | FastAPI + Uvicorn |
| IA en tiempo real | Gemini Live API (audio nativo, `BidiGenerateContent`) |
| Transporte | Proxy WebSocket `/ws/live` |
| Configuración | `pydantic-settings` (`.env`) |
| Paquetes | uv |
| Despliegue | Docker → Google Cloud Run |

## Ejecutar en local

```bash
cp .env.example .env        # completar GEMINI_API_KEY (nunca se versiona)
uv sync
uv run python main.py        # http://localhost:8000/api/v1/health
```

Con Docker:

```bash
docker build -t lazarus-backend .
docker run --env-file .env -p 8000:8000 lazarus-backend
```

## Protocolo del WebSocket `/ws/live`

```
[app móvil] ──WS /ws/live──> [backend: proxy] ──WSS──> [Gemini Live API]
                                (API key solo aquí)
```

1. La app abre `ws://<backend>/ws/live` y envía como **primer frame** (en ≤ 15 s):

   ```json
   {"type": "start", "language": "es", "voice": "Charon",
    "assistantName": "Aria", "userName": "Andrés",
    "verbosity": "concise", "describing": true}
   ```

   Solo `type` es obligatorio; el resto tiene valores por defecto.
2. El backend abre la conexión con Gemini y le envía el `setup` (modelo, voz, prompt de
   sistema por idioma, declaraciones de funciones, detección automática de voz). Gemini
   responde `{"setupComplete": {}}` y el backend lo reenvía a la app.
3. Desde ahí el proxy reenvía todo sin modificarlo:
   - App → Gemini: `realtime_input` (audio PCM 16 kHz en base64, imágenes JPEG),
     `client_content` (texto) y `tool_response`.
   - Gemini → app: `serverContent` (audio 24 kHz, transcripciones, `interrupted`,
     `turnComplete`) y `toolCall`.

**Códigos de cierre**

| Código | Causa |
| --- | --- |
| 1008 | No llegó el frame `start` a tiempo, o el primer frame no es `{"type":"start"}` |
| 1011 | Falta la API key en el servidor, falló la conexión con Gemini o Gemini cerró la sesión. El motivo nunca incluye la API key. |

## Variables de entorno

| Variable | Descripción |
| --- | --- |
| `GEMINI_API_KEY` | API key de Gemini (Developer API). Solo en el servidor. |
| `GEMINI_LIVE_MODEL` | Modelo Live con audio nativo |
| `GEMINI_LIVE_VOICE` | Voz por defecto |
| `HOST`, `PORT`, `DEBUG` | Servidor |
| `CORS_ORIGINS` | Orígenes HTTP permitidos (lista JSON) |

## Flujo de trabajo (GitFlow)

- `main`: versiones publicadas (etiquetas `vX.Y.Z`).
- `develop`: integración del sprint.
- `feature/LAZA-<n>-<descripcion>`: una rama por historia de usuario o tarea de Jira.
- `release/vX.Y.Z` y `hotfix/LAZA-<n>-…` según la estrategia GitFlow del proyecto.

Commits: `LAZA-<n> <verbo en presente> <qué>`.
