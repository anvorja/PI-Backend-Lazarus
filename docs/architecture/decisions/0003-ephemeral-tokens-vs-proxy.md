# ADR 0003 — Conexión del cliente con Gemini Live: proxy WebSocket vs. ephemeral tokens

- **Estado:** Aceptado (provisional) — 2026-06-06 · **Actualizado 2026-10-29:** se implementa la opción B con el proxy como respaldo (HU-031, LAZA-67). Ver la sección final.
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

---

## Actualización 2026-10-29 — Opción B implementada, con el proxy de respaldo (HU-031)

**Disparador cumplido:** el 28-oct Render suspendió el backend por agotar la transferencia
del plan gratuito (hallazgo 47): el audio y la cámara de cada sesión pasaban por el
servidor en los dos sentidos. Es el segundo disparador de esta ADR.

**Verificación del bloqueo de la configuración (29-oct, contra la API real):**
- Token creado con `auth_tokens.create` (SDK `google-genai`, `api_version` v1alpha),
  `uses: 1`, `live_connect_constraints` con el modelo y la configuración, y
  `lock_additional_fields: []`.
- El cliente se conectó a `…BidiGenerateContentConstrained?access_token=…` (v1alpha y v1beta)
  y envió un `setup` con **otro** system prompt: Gemini respondió siguiendo el del token, con y
  sin `lock_additional_fields`.
- Con el setup completo de Lazarus (prompt, funciones, voz, proactividad, transcripciones)
  el asistente llamó a `get_time` con normalidad.
- El segundo uso del mismo token se rechazó: "Token has been used too many times".

**Diseño:**
- `POST /api/v1/live/token` aplica las reglas del piloto antes de emitir (servicio abierto,
  teléfono aprobado, horario y minutos del día) y responde 403 con el mismo código de cierre
  del proxy (4006–4010) si rechaza. La vida del token es `LIVE_TOKEN_TTL_S` (30 min), sin
  pasar de los minutos que le quedan al teléfono; un token sin usar vence al minuto.
- La sesión queda registrada con `mode = "direct"`. La app informa el fin con
  `POST /api/v1/live/sessions/{id}/end`; si no lo hace, la sesión se cierra al pedir el
  siguiente token, contada hasta la vida del token.
- La app usa el proxy `/ws/live` si el endpoint responde 404 (`LIVE_DIRECT_ENABLED=false`),
  502 o no responde, o si la conexión directa falla antes de abrir.
- `LIVE_DIRECT_ENABLED` (por defecto `false`) permite activarlo y desactivarlo desde Render
  sin publicar otra APK.

**Lo que se pierde en el modo directo (aceptado):**
- "Cerrar sesión" desde el panel no corta una sesión directa en curso: el teléfono no puede
  abrir la siguiente y la sesión termina, a más tardar, al vencer el token.
- Los bytes de audio y cámara ya no se miden en el backend: es justo el objetivo. La
  comparación del criterio 4 se hace con la transferencia del mes del panel (HU-051).

