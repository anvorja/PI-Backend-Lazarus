# System prompt del copiloto — versionado

> Registro de versiones del prompt de sistema (`app/prompts/companion.py`). Cada cambio de comportamiento sube `PROMPT_VERSION` y agrega aquí un bloque `## vX.Y.Z — fecha — motivo`, del más reciente al más antiguo. El backend registra la versión en el log al iniciar cada sesión.

## v1.4.0 — 2026-09-23 — Lista cerrada de idiomas: sin función para uno no soportado (LAZA-32 · HU-006)

**Motivo:** con v1.3.0 el asistente siguió diciendo "Idioma cambiado a ruso" antes de
recibir el error de `set_language`: con audio nativo, Gemini habla mientras llama a la
función. Esperar el resultado no basta; hay que evitar la llamada.

**Cambio:** la regla de idioma (última de las reglas base, 5 idiomas) nombra los idiomas
disponibles y pide no llamar a `set_language` si la persona pide otro, sino responder
en una frase que aún no está disponible y cuáles hay. La respuesta de error de la app
se mantiene como red de seguridad.

## v1.3.0 — 2026-09-23 — Confirmar un cambio solo después del resultado de la función (LAZA-32 · HU-006)

**Motivo:** en la prueba CP-LAZA-32, al pedir un idioma no soportado (ruso), el
asistente dijo "El idioma se ha cambiado a ruso" antes de recibir el resultado de
`set_language` y luego se corrigió. Gemini habla mientras llama a la función.

**Cambio:** en los 5 idiomas, la regla "tras cualquier función, confirma en una sola
frase corta" pasa a: esperar el resultado antes de hablar del cambio; si es `ok`,
confirmarlo en una frase corta; si es un error, no decir que se hizo y explicar qué
pasó. El resto del prompt es igual al de v1.2.0.

## v1.2.0 — 2026-09-23 — Modo solo audio sin permiso de cámara (LAZA-32 · HU-006)

**Motivo:** si la persona no da permiso de cámara, la sesión sigue solo con audio
(HU-006, regla 2). El asistente debe avisarlo y no describir lo que no ve.

**Cambio:** nuevo modificador `_CAMERA_OFF` (5 idiomas), que se agrega cuando la app
envía `camera: false` en el frame `start`: al saludar con `[INICIO]` avisa en una frase
que funcionará solo con audio; no describe el entorno ni da alertas visuales; si le
preguntan qué hay delante, explica que la cámara no está disponible. Sin la bandera, el
prompt es igual al de v1.1.0.

## v1.1.0 — 2026-09-23 — Idioma fijo salvo pedido explícito (LAZA-31 · HU-005)

**Motivo:** en la prueba en teléfono de HU-005, con ruido o frases cortas, la
transcripción de la voz de la persona salió en otros idiomas (p. ej. italiano). Se
refuerza la última regla base en los 5 idiomas: el asistente habla siempre en el idioma
configurado (español por defecto), aunque el audio suene a otro idioma o tenga ruido, y
solo lo cambia si la persona lo pide de forma explícita (función `set_language`).

**Cambio:** regla final de las reglas base ("Habla siempre en español." y equivalentes).
El resto del prompt no cambia.

## v1.0.0 — 2026-09-23 — Versión formal del copiloto de movilidad (LAZA-29 · HU-003)

**Motivo:** fijar como versión 1.0.0 el prompt con el que se prueba el piloto, con
número de versión en el código (`PROMPT_VERSION`) y registrado en el log de cada sesión.

**Composición** (`get_live_system_prompt`, en este orden):

1. Identidad: nombre del asistente (por defecto "Aria"), presentación única al recibir
   `[INICIO]`, recordatorio de que no sustituye el bastón ni el perro guía, uso de las
   funciones de personalización.
2. Nombre de la persona usuaria, solo si ya lo dijo (`set_user_name`).
3. Comandos de voz y modos de silencio (reunión y silencio total), ayuda y repetir.
4. Tareas a petición: leer texto, describir la escena, buscar un objeto.
5. Reglas base de navegación (abajo).
6. Modificadores opcionales: nivel de detalle "detallado" y descripciones en pausa.

**Reglas base** (iguales en los 5 idiomas: `es`, `en`, `fr`, `pt`, `it`):

| Regla | Contenido |
| --- | --- |
| P1 — Seguridad | Advertencias primero y siempre; empiezan por la palabra de peligro; orden tipo, dirección, distancia; máximo 6 palabras |
| P2 — Orientación | Dirección en horas de reloj (12 al frente, 3 derecha, 9 izquierda) y distancia en pasos |
| P3 — Contexto | Frases cortas (10–12 palabras), sin "veo que" ni "parece que" |
| No repetir | Solo lo nuevo o lo que cambia; silencio si la escena no cambia |
| Exactitud | Si no está seguro, lo dice ("quizá", "no seguro") o calla; nunca inventa obstáculos, distancias ni textos |
| Preguntas | Responde solo lo preguntado y no retoma las descripciones hasta que haya silencio |
| Tono | Sin lenguaje subjetivo; solo hechos útiles para moverse |

**Señales internas** que interpreta el prompt: `[INICIO]` (presentación), `[VOZ]` (muestra
corta tras cambiar de voz), `[MIC_ON]` (confirmación corta al salir de silencio total o
al retomar tras una pausa).

**Pruebas:** `tests/test_prompts.py` verifica la composición en los 5 idiomas, el orden de
las partes, los modificadores y que esta versión esté documentada aquí.
