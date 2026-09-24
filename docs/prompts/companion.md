# System prompt del copiloto — versionado

> Registro de versiones del prompt de sistema (`app/prompts/companion.py`). Cada cambio de comportamiento sube `PROMPT_VERSION` y agrega aquí un bloque `## vX.Y.Z — fecha — motivo`, del más reciente al más antiguo. El backend registra la versión en el log al iniciar cada sesión.

## v1.8.0 — 2026-09-24 — Pausar descripciones exige set_descriptions y buscar sugiere girar (LAZA-36 · HU-010)

**Motivo:** en la prueba CP-LAZA-36 (v1.7.0), a "deja de describir" el asistente
respondió "Entendido. Pauso las descripciones." sin llamar a `set_descriptions`, así que
la pausa no se guardó. Al reabrir, el saludo no la mencionó y "vuelve a describir"
tampoco llamó a la función. Es la misma falla de v1.5.0, en una función que no estaba
nombrada en la identidad. Además, al buscar un objeto que no estaba a la vista dijo
"No veo ninguna bicicleta" sin sugerir girar el teléfono.

**Cambio (5 idiomas):**

- Identidad: nombra `set_descriptions` (dejar de describir o volver a describir) y
  añade "descripciones" a la lista de ajustes que no se pueden confirmar sin llamar a
  su función.
- Buscar un objeto: si no está a la vista, en la misma respuesta sugiere siempre
  girar despacio el teléfono.

El resto del prompt es igual al de v1.7.0.

## v1.7.0 — 2026-09-24 — Ayuda completa, repetir tal cual y pausa con alertas de seguridad (LAZA-36 · HU-010)

**Motivo:** HU-010 pide que la ayuda enumere los comandos disponibles, que "repite"
repita la última respuesta y que, con las descripciones en pausa, las alertas P1 se
den siempre. La ayuda no mencionaba las tareas a petición y "repetir" pedía hacerlo
"de forma breve". La pausa pedida en mitad de una sesión no recordaba las alertas de
seguridad: eso solo estaba en el modificador `_DESCRIPTIONS_PAUSED`, que se aplica al
abrir la sesión siguiente.

**Cambio (5 idiomas):**

- Comandos: "repetir" repite la última respuesta con las mismas palabras, como
  excepción explícita a la regla de no repetir.
- Pausa de descripciones: mientras dure la pausa no describe por iniciativa propia,
  pero responde lo que se le pregunte y da siempre las advertencias de seguridad de la
  regla 1.
- Ayuda: enumera también las tareas a petición (leer un texto, describir dónde está,
  buscar un objeto).
- `_DESCRIPTIONS_PAUSED`: al presentarse con `[INICIO]` avisa que las descripciones
  están en pausa y que se pueden reanudar.

El resto del prompt es igual al de v1.6.0.

## v1.6.0 — 2026-09-24 — Cada ajuste por voz exige su función (LAZA-35 · HU-009)

**Motivo:** en la prueba CP-LAZA-35 (v1.5.0), el asistente dijo "Ajusto el nivel de
detalle" y "Cambio a descripciones detalladas" sin llamar a `set_verbosity`, así que
el ajuste no se guardó. En una sesión en inglés, a "Speak Spanish" respondió en
español sin llamar a `set_language`. Tras `[IDIOMA]` dijo "I will speak in English
now" y luego, en español, que hablaría en español.

**Cambio (5 idiomas):**

- Identidad: nombra `set_verbosity` (más breve o más detalle) y `set_system_cues`
  (silenciar o activar avisos) junto a las demás funciones. Prohíbe decir que se
  cambió un ajuste sin haber llamado a su función, porque sin ella el cambio no se
  aplica ni se guarda.
- `[IDIOMA]`: decir solo la frase de confirmación, sin mencionar otro idioma.

El resto del prompt es igual al de v1.5.0.

## v1.5.0 — 2026-09-24 — Saludo por nombre y confirmación corta al cambiar de idioma (LAZA-35 · HU-009)

**Motivo:** HU-009 pide que el asistente salude a la persona por su nombre al abrir la
app (criterio 4) y que cada cambio se confirme en una frase corta (regla 4). Al cambiar
de idioma la sesión se reconecta y el asistente repetía la presentación completa.

**Cambio:**

- Identidad (5 idiomas): nuevo sentinela `[IDIOMA]`. La app lo envía al reconectar tras
  `set_language`; el asistente no repite la presentación y confirma en una sola frase
  corta, en el idioma nuevo, que ahora hablará en él.
- Nombre de la persona (5 idiomas): al presentarse con `[INICIO]` la saluda por su
  nombre. Se corrige "Diríjete" → "Dirígete".

El resto del prompt es igual al de v1.4.0.

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
