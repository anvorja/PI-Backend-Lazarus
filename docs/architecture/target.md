# Backend — Arquitectura objetivo

> Destino al que apunta el [plan de migración](../../../lazarus-plan.md). El estado actual está en [current.md](current.md).

## Resumen en una línea

Servicio ligero que (a) durante las Fases 1-5 hace de **proxy WebSocket** entre el cliente y Gemini Live, y (b) en la Fase 8 final, queda reducido a un **servicio sin estado** que emite ephemeral tokens, envuelve Google Places y registra telemetría — porque el cliente Flutter habla directo con Gemini.

## Diagrama de la Fase 2 (transitorio)

```
[Cliente web/Flutter]
  │  Socket.IO o WebSocket nativo
  ▼
[Backend proxy]                ┌──────────────┐
  ├─ por cada sid ───────────► │  Gemini Live │
  │     sesión persistente     │   API (WS)   │
  ▼                            └──────────────┘
[Tools]
  ├─ get_nearby_places  ─────► Google Places API
  ├─ set_mode(in/out)    (estado en memoria por sid)
  └─ log_event           (telemetría)
```

## Diagrama de la Fase 8 (definitivo)

```
[Cliente Flutter]
  │
  ├─ POST /session/token   ─► [Backend ligero]
  │                              ├─ emite ephemeral token Gemini
  │                              ├─ firma system prompt
  │                              └─ devuelve {token, prompt_id}
  │
  ├─ WebSocket directo  ─────► Gemini Live API
  │
  ├─ POST /places/nearby  ──► [Backend] ──► Google Places
  └─ POST /telemetry      ──► [Backend] ──► Storage
```

El backend deja de manejar streams pesados. Solo emite tokens, hace de wrapper de Places (con caché/rate limit) y recibe eventos de telemetría (alertas críticas).

## Decisiones técnicas vivas

Las decisiones grandes (proxy vs ephemeral, Flutter vs RN, modelo Gemini elegido) viven en `decisions/`.

## Endpoints/handlers proyectados

Fase 2 (Socket.IO sobre el backend actual):

- `start_live_session` / `stop_live_session`
- `client_audio_chunk` (PCM/Opus)
- `client_video_frame` (JPEG base64 o WebRTC track)
- `client_location` (lat/lng cada >10 m)
- `assistant_audio_chunk` / `assistant_text` / `assistant_interrupt` (salientes)

Fase 8 (REST sobre el backend ligero):

- `POST /session/token` — ephemeral token de Gemini.
- `POST /places/nearby` — wrapper Google Places.
- `POST /places/route` — wrapper Walking Directions.
- `POST /telemetry/event` — logs de alertas P1.

## Capacidades conversacionales (Fase 3)

System prompt versionado en `docs/prompts/companion.md`. Tres niveles:

- **P1 Alertas críticas** — interrumpe siempre.
- **P2 Navegación** — orientación tipo reloj.
- **P3 Disfrute** — descripción ambiental solo si seguro.

Modo `indoor` / `outdoor` activable por voz o por pérdida de GPS.

## Riesgos arquitectónicos a vigilar

- Costo Gemini Live por minuto en sesiones largas.
- Cuota Google Places (mitigado con caché).
- Sesiones persistentes en backend Python: límite de archivos abiertos, memoria por `sid` con buffer de audio.
- Cuando se migre a Flutter directo, asegurarse de que ephemeral tokens caducan rápido y son por usuario.
