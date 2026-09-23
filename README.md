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
