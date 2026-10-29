# ADR 0001 — Cerebro del asistente: Gemini Live vs. pipeline AWS Rekognition + DeepSeek + Polly

- **Estado:** Aceptado e implementado — 2026-06-05 (retrospectivo)
- **Decide:** equipo Lazarus
- **Afecta a:** arquitectura completa del backend, latencia, costo, experiencia de usuario
- **Relacionado:** `lazarus-plan.md`, `docs/architecture/current.md`, `propuesta-gemini-live.pdf`,
  ADR `0003-ephemeral-tokens-vs-proxy.md`

> Este ADR se redacta de forma **retrospectiva**: documenta una decisión ya tomada y
> ejecutada (el legacy AWS ya no existe en el repo). Se escribe para dejar constancia del
> "por qué" de cara al futuro.

---

## Contexto

La versión original de Lazarus era una **herramienta de detección** request/response:

```
[Frontend] --frame 220×140 cada 2 s--> [Backend Socket.IO]
   → AWS Rekognition (detección de objetos/etiquetas)
   → DeepSeek (genera frase descriptiva a partir de las etiquetas)
   → AWS Polly (texto → MP3)
   → devuelve audio al frontend
```

Limitaciones estructurales de ese modelo:

- **Latencia ~2 s** end-to-end por la cadena de 3 servicios secuenciales.
- **Sin micrófono de entrada**: el usuario no podía preguntar nada; flujo unidireccional.
- **Sin interrupción**: el audio se reproducía entero aunque la situación cambiara.
- **Sin contexto conversacional**: cada frame se procesaba aislado; el sistema no
  "recordaba" nada ni mantenía una conversación.
- **Detección, no comprensión**: Rekognition devuelve etiquetas ("person", "chair"), no
  una interpretación útil de la escena para orientación/seguridad.
- **Tres proveedores** (AWS Rekognition, AWS Polly, DeepSeek) → tres puntos de fallo,
  tres facturaciones, tres SDKs.

El documento `propuesta-gemini-live.pdf` proponía un cambio de paradigma: dejar de "detectar
objetos" y construir un **acompañante digital conversacional** sobre un modelo
multimodal en tiempo real.

---

## Decisión

**Reemplazar todo el pipeline AWS Rekognition + DeepSeek + Polly por Gemini Live API**
(audio nativo, WebSocket bidireccional), y eliminar el stack legacy del repo.

El backend pasa a ser un **proxy WebSocket** (`/ws/live`) que mantiene la API key
server-side e intermedia entre cliente y Gemini.

---

## Justificación

| Criterio | Pipeline AWS + DeepSeek (anterior) | Gemini Live (elegido) |
|---|---|---|
| Latencia | ~2 s (3 servicios en cadena) | <1 s (streaming nativo) |
| Entrada de voz del usuario | ❌ no existe | ✅ micrófono en streaming |
| Interrupción natural | ❌ no | ✅ el usuario habla y el modelo se calla |
| Contexto conversacional | ❌ frame aislado | ✅ sesión persistente con memoria |
| Comprensión de escena | ➖ etiquetas sueltas | ✅ interpretación multimodal en lenguaje natural |
| Proveedores | 3 (Rekognition + Polly + DeepSeek) | 1 (Google) |
| Audio | Polly (TTS sobre texto) | audio nativo del modelo (más natural, interrumpible) |
| Personalización por voz | ❌ | ✅ function calling (nombre, idioma, voz, verbosidad…) |
| Idiomas | multi-idioma vía prompts | 5 idiomas (es/en/fr/pt/it) |

El cambio no es incremental sino de **paradigma**: de "describir frames" a "acompañar en
una conversación". Gemini Live cubre en un solo servicio lo que antes requería tres, con
latencia menor y capacidades (voz de entrada, interrupción, conversación) imposibles en
el modelo anterior.

---

## Consecuencias

**Positivas:**

- Experiencia conversacional real, interrumpible, en <1 s.
- Una sola dependencia (`google-genai` + `websockets`); se eliminaron `boto3`, el SDK de
  OpenAI/DeepSeek, OpenCV, NumPy, Pillow.
- Backend más simple: un proxy WebSocket en vez de orquestar 3 servicios.
- La API key vive solo server-side (ver ADR 0003 para la evolución de este punto).
- System prompt como única fuente de verdad del comportamiento, versionado en
  `app/prompts/companion.py`.

**Negativas / a vigilar:**

- **Dependencia de un solo proveedor** (Google) para todo el núcleo.
- **Costo por minuto de streaming** desconocido a escala — riesgo abierto, pendiente de
  medir con tráfico real (ver `lazarus-plan.md`).
- El endpoint requiere **v1alpha** (necesario para `proactivity`; v1beta lo rechaza con
  close 1007) → superficie de API menos estable.
- El backend como proxy de streaming es **con estado**, lo que condiciona el despliegue
  (ver ADR 0003 / Fase F3).

**Ejecución (ya realizada):**

- Eliminados `image_service.py`, `text_service.py`, `voice_service.py`,
  `gemini_service.py` (fase single-shot intermedia), `handlers.py`, `constants.py`.
- `main.py` y `app/main.py` migrados de Socket.IO a FastAPI puro con WebSocket nativo.
- `config.py`, `pyproject.toml` y `.env.example` reducidos a lo de Gemini + infra.

---

## Alternativas consideradas

- **Mantener AWS y solo cambiar DeepSeek por otro LLM** — descartada: no resuelve la
  latencia, la falta de voz de entrada ni la ausencia de conversación/interrupción.
- **Gemini en modo single-shot (request/response multimodal)** — fase intermedia
  realmente implementada (`gemini_service.describe_frame`) y luego descartada: mejoraba
  la calidad pero seguía sin voz de entrada ni interrupción. Se superó con Gemini Live.
- **OpenAI Realtime / otros modelos de voz en tiempo real** — no evaluados en
  profundidad; Gemini se eligió por capacidad multimodal (visión + audio) en una sola
  sesión y por encajar con el ecosistema previsto (Places, Flutter, tokens efímeros).
