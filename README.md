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

**Códigos de cierre** (la app decide con ellos si reconecta sola o avisa a la persona)

| Código | Causa | Qué hace la app |
| --- | --- | --- |
| 1008 | No llegó el frame `start` a tiempo, o el primer frame no es `{"type":"start"}` | Error; aviso hablado |
| 4001 | La sesión terminó: Gemini la cerró o se cumplió `GEMINI_LIVE_MAX_SESSION_S` | Pausa; al tocar la pantalla retoma con una confirmación corta |
| 4002 | Falló la red o la conexión con Gemini | Reintenta sola hasta 3 veces (1 s, 2 s, 4 s) |
| 4003 | Cuota de la API agotada | Aviso hablado; no reintenta |
| 4004 | El servidor no tiene `GEMINI_API_KEY` | Aviso hablado; no reintenta |
| 4005 | La cuenta de Gemini se quedó sin saldo (créditos, facturación o tope de gasto mensual) | Aviso hablado ("se quedó sin saldo"); no reintenta |

El motivo de cierre nunca incluye la API key.

**Eventos de sesión (HU-015):** el logger `lazarus.telemetry` escribe una línea JSON al
iniciar y al terminar cada sesión (id corto, versión del prompt, idioma, voz, duración,
código de cierre y mensajes en cada sentido). Nunca lleva audio, imágenes,
transcripciones, el nombre de la persona ni la API key.

## Configuración de la sesión con Gemini

| Parámetro | Valor |
| --- | --- |
| Modelo | `GEMINI_LIVE_MODEL` (audio nativo) |
| Voz por defecto | `GEMINI_LIVE_VOICE` (la app puede cambiarla por voz) |
| Idioma por defecto | `GEMINI_LIVE_LANGUAGE` si la app no lo envía |
| Respuesta | Solo audio, temperatura 0,3 |
| Detección de voz | Automática; si la persona habla, el asistente se interrumpe (`START_OF_ACTIVITY_INTERRUPTS`) |
| Audio proactivo | Activo: puede avisar de riesgos sin que se le pregunte |
| Transcripción de entrada | Activa |

## Variables de entorno

| Variable | Descripción |
| --- | --- |
| `GEMINI_API_KEY` | API key de Gemini (Developer API). Solo en el servidor. |
| `GEMINI_LIVE_MODEL` | Modelo Live con audio nativo |
| `GEMINI_LIVE_VOICE` | Voz por defecto |
| `GEMINI_LIVE_LANGUAGE` | Idioma por defecto (`es`, `en`, `fr`, `pt`, `it`) |
| `GEMINI_LIVE_MAX_SESSION_S` | Duración máxima de la sesión en segundos; `0` = sin límite propio (valor corto solo para pruebas) |
| `HOST`, `PORT`, `DEBUG` | Servidor |
| `CORS_ORIGINS` | Orígenes HTTP permitidos (lista JSON) |

## Panel del piloto y control de acceso (HU-043 a HU-046)

El backend expone la API del panel en **`/api/v1/admin/*`**. La interfaz vive aparte, en `devices-laza-admin-ui` (React y TypeScript, publicada en Netlify), que reenvía `/api/*` a este backend con un proxy: para el navegador es el mismo origen, así que la cookie del refresh viaja con `SameSite=Strict` y no hace falta CORS.

- **Servicio:** interruptor general y horario de las jornadas (hora de Colombia). `LIVE_ENABLED=false` en Render manda sobre todo y no deja abrir ninguna sesión.
- **Dispositivos:** cada teléfono se registra solo la primera vez y queda pendiente. Desde el panel se aprueba, se nombra con un seudónimo, se le pone un límite de minutos por día, se le piden o se le limpian los logs, se le cierra la sesión o se deshabilita.
- **Logs de campo:** al tocar Detener, la app sube lo nuevo de su log, notas, recorrido GPS y telemetría. El panel los descarga unidos en un .zip y muestra la latencia voz a voz.
- **Perfiles de ruta (HU-022):** cada perfil curado (una estación, un sentido, sus puntos en orden) se guarda en la base de datos, no en el repositorio, porque lleva coordenadas. Se carga con `uv run python scripts/load_route.py perfil.json --url <backend> --user <admin>`, que pide la clave por teclado, o con `PUT /api/v1/admin/routes/{slug}`. La app lo descarga con su token (`GET /api/v1/devices/me/routes`, solo teléfonos aprobados).

| Variable | Para qué |
| --- | --- |
| `DATABASE_URL` | Postgres de Neon (`postgresql://…`). Sin ella se usa SQLite, que en Render se pierde en cada despliegue. |
| `DEVICE_AUTH_REQUIRED` | `true` cuando todos los teléfonos tengan la versión que se registra. |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Primer administrador; la contraseña se guarda con Argon2. |
| `ADMIN_JWT_SECRET` | Al menos 32 caracteres aleatorios; sin ella el panel no deja entrar. |
| `LOG_RETENTION_DAYS` | Días que se guardan los logs (30 por defecto). |

Códigos de cierre del control de acceso: 4006 en pausa o fuera de horario, 4007 pendiente de aprobación, 4008 deshabilitado, 4009 minutos del día agotados, 4010 sesión cerrada desde el panel.

## Flujo de trabajo (GitFlow)

- `main`: versiones publicadas (etiquetas `vX.Y.Z`).
- `develop`: integración del sprint.
- `feature/LAZA-<n>-<descripcion>`: una rama por historia de usuario o tarea de Jira.
- `release/vX.Y.Z` y `hotfix/LAZA-<n>-…` según la estrategia GitFlow del proyecto.

Commits: `LAZA-<n> <verbo en presente> <qué>`.
