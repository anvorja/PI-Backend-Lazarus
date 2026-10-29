# ADR 0003 — Conexión del cliente con Gemini Live: proxy WebSocket vs. ephemeral tokens

- **Estado:** Aceptado (provisional) — 2026-06-06
- **Decide:** equipo Lazarus
- **Afecta a:** cliente Flutter (Fase F1), backend, costo e infraestructura
- **Relacionado:** `lazarus-plan.md`, `docs/architecture/current.md`, `docs/architecture/web-limits.md`

---

## Contexto

El cliente Flutter necesita una sesión de **Gemini Live API** (WebSocket bidireccional,
audio nativo). El invariante de seguridad del proyecto es **innegociable**: la
`GEMINI_API_KEY` **nunca** puede llegar al dispositivo del usuario. Una key embebida en
el APK/IPA es extraíble con herramientas triviales y permitiría a un tercero consumir la
cuota a nuestro costo.

Existen dos formas de conectar la app a Gemini sin exponer la key:

### Opción A — Proxy WebSocket `/ws/live` (lo ya implementado)

```
[App Flutter] ──WS /ws/live──> [Backend] ──WS──> [Gemini Live]
                               (la key vive aquí)
```

El cliente habla solo con **nuestro** backend; el backend reenvía audio/video/respuestas
hacia Gemini y de vuelta. Es **exactamente** el flujo que el frontend web ya usa hoy
(frame `start`, `toolCall`, prompts server-side). Flutter reusaría el mismo endpoint,
protocolo y prompts; solo cambia el lenguaje del cliente.

### Opción B — Ephemeral tokens (conexión directa)

```
[Backend] ──pide token efímero (usa la key 1 vez)──> [Gemini]
    └── entrega token de corta vida ──> [App Flutter] ──WS directo──> [Gemini Live]
```

El backend usa la key real para obtener un **token efímero** (corta vida, uso acotado) y
se lo entrega al cliente. La app se conecta **directo** a Gemini con ese token, sin pasar
streams por nuestro servidor. La key sigue sin salir del backend.

---

## Decisión

**Secuencia acordada (2026-06-06):**

1. **Durante toda la construcción de Flutter (Fase F1): Opción A (proxy `/ws/live`).**
   Riesgo cero, sin backend nuevo, el prompt nunca lo ve el cliente. Se valida paridad
   de features con el cliente ya probado.
2. **Una vez Flutter corra bien en desarrollo: abordar la Opción B (ephemeral tokens)**
   como optimización, validada con las mediciones de latencia/costo recogidas en F1.

No se construyen ephemeral tokens de forma anticipada (antes de que Flutter sea estable
en dev).

> **Nota — esto NO es lo mismo que la autenticación de usuarios.** "¿Quién puede usar la
> app?" (allowlist de correos / Firebase Auth / base de datos) es un problema **aparte y
> ortogonal**: decide *quién entra*, no *cómo se conecta a Gemini*. Las dos capas
> conviven: cuando se adopte B, el endpoint que emite el token efímero **primero
> comprueba la autenticación** (¿este correo está autorizado?) y solo entonces emite el
> token. Esa comprobación es un check **único al abrir la sesión** (milisegundos), no se
> repite por chunk de audio, así que **no afecta la latencia del streaming**. Ver Fase
> F3 del plan ("backend definitivo" / auth).

---

## Justificación

| Criterio | A — Proxy (elegido) | B — Ephemeral tokens |
|---|---|---|
| Seguridad de la key | ✅ key server-side | ✅ key server-side (entrega token) |
| Esfuerzo para arrancar Flutter | ✅ cero backend nuevo (ya existe) | ❌ endpoint `/session/token`, caducidad, renovación, prompt firmado |
| Latencia | ➖ doble salto (app↔backend↔Gemini) | ✅ salto directo (app↔Gemini) |
| Ancho de banda del backend | ❌ todos los streams pasan por el servidor | ✅ backend solo emite tokens |
| Escalabilidad con muchos usuarios | ❌ el backend carga cada stream | ✅ escala casi sin estado |
| Madurez / probado | ✅ funcionando hoy en web | ➖ depende de soporte de la API y trabajo nuevo |
| Riesgo | ✅ mínimo | ➖ más piezas que pueden fallar |

La Opción A permite empezar Flutter **de inmediato y sin riesgo**, validando paridad de
features con el cliente probado. La penalización de latencia/ancho de banda es real pero
**solo importa a escala**; con el volumen actual (validación, demos) es despreciable.
Construir ephemeral tokens ahora sería optimización prematura: semanas de trabajo en
caducidad/renovación/firma de prompt que quizá nunca haga falta.

## Disparadores para revisitar y migrar a B

Revisar esta ADR si se cumple alguno:

- La latencia añadida por el proxy degrada la experiencia de forma medible
  (objetivo de respuesta extremo a extremo < 1 s no se cumple por culpa del salto extra).
- El costo de ancho de banda / cómputo del backend reenviando streams se vuelve
  significativo frente al costo de Gemini.
- El número de sesiones concurrentes satura el backend (CPU/red/conexiones).
- Se prepara producción a escala (muchos usuarios simultáneos sostenidos).

Antes de migrar, confirmar que la API de Gemini Live soporta ephemeral tokens con la
vida útil y el alcance necesarios, y definir cómo se **firma el system prompt**
server-side para que el cliente no pueda manipularlo.

### Requisito crítico de la Opción B — bloquear la config en el token

En B el cliente conecta directo a Gemini y, en principio, envía el mensaje `setup`
(que incluye el **system prompt** y las tools). Para impedir que un cliente malicioso
**reescriba el prompt** (jailbreak, quitar reglas de seguridad), el token efímero debe
emitirse con la **configuración bloqueada server-side** (en Gemini Live: *connect
constraints* / config sellada al crear el token). Así, aunque el cliente mande su propio
`setup`, Gemini ignora lo que contradiga lo sellado.

- Esto da **ambas garantías a la vez**: prompt no manipulable **y** baja latencia
  (salto directo). No hay que elegir entre seguridad del prompt y rendimiento.
- El riesgo de B es **solo de implementación**: si se emite el token sin bloquear la
  config, el cliente podría inyectar su propio prompt. → **Debe verificarse y testearse
  explícitamente** que el lock está activo antes de confiar en él.
- **Pendiente de verificar** contra la versión vigente de la API de Gemini Live que el
  bloqueo de config en el token efímero está disponible con el alcance necesario.

En la Opción A este problema **ni existe**: el prompt lo inyecta el backend y el cliente
nunca lo ve.

## Consecuencias

- **F1 arranca sin tocar el backend**: el cliente Flutter usa `/ws/live` tal cual.
- El backend sigue siendo un **proxy con estado** mientras dure la Opción A (relevante
  para la elección de despliegue; ver Fase F3 del plan).
- Cuando se migre a B, el backend evoluciona a servicio ligero (`/session/token` +
  Places + telemetría), posiblemente sin estado y autoescalable (Cloud Run).
- Se debe **medir** latencia y costo durante F1 para alimentar esta decisión — ver
  riesgo "Costo Gemini Live por minuto" en `lazarus-plan.md`.

## Alternativas descartadas

- **Key embebida en el cliente** — descartada de plano: viola el invariante de seguridad.
- **Construir A y B a la vez** — descartada: duplica esfuerzo sin beneficio inmediato.
