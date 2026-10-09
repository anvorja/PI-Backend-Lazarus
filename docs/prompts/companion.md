# System prompt del copiloto — versionado

> Registro de versiones del prompt de sistema (`app/prompts/companion.py`). Cada cambio de comportamiento sube `PROMPT_VERSION` y agrega aquí un bloque `## vX.Y.Z — fecha — motivo`, del más reciente al más antiguo. El backend registra la versión en el log al iniciar cada sesión.

## v1.15.0 — 2026-10-08 — Sesión sin imágenes con la pantalla bloqueada y sin rutas (LAZA-45 · HU-017)

**Motivo:** en la caminata de 10 minutos con la pantalla bloqueada (CP-LAZA-45, 8 de
octubre) la sesión siguió viva, pero el aviso '[SIN_CAMARA]' a mitad de sesión no
bastó. A los pocos segundos el asistente dijo "[CAMARA] Vuelvo a ver." sin que la app
lo enviara y siguió describiendo la última foto (charcos, carros, un desnivel) como si
fuera lo que la persona tenía delante, mientras ella caminaba. Además le pidió llegar a
una dirección e inventó giros ("en unos 10 pasos giras a la izquierda") hasta decir
"¡Has llegado a tu destino!". Tras una reconexión por un corte de los datos móviles, se
negó a dar la ubicación "porque la cámara está bloqueada".

**Cambio en la app:** al bloquear la pantalla se abre una sesión nueva con
`screenLocked: true` en el frame `start`, sin ninguna imagen en su historial; al
desbloquear (tras 1,5 s, por si fue sin querer) se abre otra con cámara. '[SIN_CAMARA]'
y '[CAMARA]' son ahora el primer mensaje de cada sesión.

**Cambio en el prompt (5 idiomas):**
- PANTALLA BLOQUEADA: las marcas las envía la app al empezar una sesión; el asistente
  nunca las dice ni las inventa, y no dice que vuelve a ver sin recibir '[CAMARA]'.
- Nuevo bloque SESIÓN CON LA PANTALLA BLOQUEADA (solo en esas sesiones, en lugar de
  OBSERVACIÓN): no tiene ninguna imagen, todo lo que diga del entorno sería inventado;
  no describe ni da indicaciones aunque se lo pidan; la ubicación no depende de la
  cámara y debe llamar a get_location cada vez.
- Nuevo bloque SIN RUTAS (en todas las sesiones): no tiene mapas ni rutas; si piden
  llegar a un lugar, dice dónde está ahora y que todavía no puede guiar hasta allá; no
  inventa giros, cuadras ni distancias ni dice que ya llegó.

El resto del prompt es igual al de v1.14.0.

## v1.14.0 — 2026-10-07 — Pantalla bloqueada: '[SIN_CAMARA]' y '[CAMARA]' (LAZA-45 · HU-017)

**Motivo:** con HU-017 la sesión sigue con la pantalla bloqueada (servicio en primer
plano de Android), pero Android detiene la cámara mientras la app no está visible. Sin
aviso, el asistente seguiría describiendo la última imagen como si fuera lo que la
persona tiene delante.

**Cambio (5 idiomas):** nuevo bloque PANTALLA BLOQUEADA. Con '[SIN_CAMARA]' el asistente
dice solo "Sigo contigo, pero sin ver.", deja de describir y de dar alertas visuales, y
si le preguntan qué hay explica que la cámara está en pausa. Con '[CAMARA]' dice solo
"Vuelvo a ver." y sigue normal. La app deja de enviar '[OBSERVA]' mientras la cámara
está en pausa.

El resto del prompt es igual al de v1.13.0.

## v1.13.0 — 2026-10-06 — Ciclo de observación con '[OBSERVA]' (LAZA-107 · HU-040)

**Motivo:** Gemini Live no habla si nadie le habla (CP-LAZA-36): la imagen de la cámara
no abre un turno. Sin eso, las alertas de seguridad (regla 1) no llegan mientras la
persona camina en silencio.

**Spike (`scripts/spike_observa.py`, 6 de octubre):** recorridos reales de las pruebas
(escalera con un gato, parque y calle, parqueadero de un centro comercial y una escena
quieta) reproducidos a 1 foto por segundo, con `[OBSERVA]` cada 3 s por el flujo de la
cámara. El asistente avisó sin que nadie hablara ("Gato, abajo, un paso", "Escaleras,
al frente, un paso", "Bordillo, al frente, un paso"), con una latencia mediana de 1,6 s
(percentil 90: 2,3 s), y habló en el 33 % de los sentinelas con descripciones activas.
Con las descripciones en pausa habló más (54 %), describiendo flechas y pisos: la regla
se endureció.

**Cambio (5 idiomas):** nuevo bloque OBSERVACIÓN. '[OBSERVA]' no lo dice la persona:
no se menciona ni se responde como pregunta. Al recibirlo, el asistente mira la imagen
más reciente y habla solo si (a) hay un riesgo para caminar a pocos pasos (alerta de 6
palabras como máximo, con tipo, dirección y distancia) o (b) con descripciones activas,
apareció algo nuevo que sirve para orientarse. Si no, no dice nada. Con las
descripciones en pausa, solo (a).

**Ajuste tras la prueba en el teléfono (CP-LAZA-107, 6 de octubre):** con descripciones
activas dio una descripción larga de un pasillo; lo nuevo se dice en una frase de 8
palabras como máximo. La app baja el periodo de `[OBSERVA]` de 3 a 2 s: con 3 s más la
respuesta, un aviso llegaba hasta 7 s después de que el obstáculo apareció.
Con las descripciones pausadas a mitad de la sesión, el asistente seguía describiendo
("Pasillo estrecho al frente"): no recordaba la pausa. La app envía ahora
`[OBSERVA_RIESGOS]` cuando están en pausa, y el prompt lo trata como `[OBSERVA]` solo
para riesgos.

El resto del prompt es igual al de v1.12.0.

## v1.12.0 — 2026-10-05 — Lados según la imagen más reciente (LAZA-109 · HU-041)

**Motivo:** en la prueba de CP-LAZA-39 el asistente confundió izquierda y derecha
durante un recorrido. El spike de HU-041 (`scripts/spike_lateralidad.py`, 47 preguntas
sobre fotos reales de las pruebas) mostró que, viendo la foto, el modelo acierta el
lado el 98 % de las veces con el prompt actual, y que ni un marco de referencia más
largo ni franjas IZQ/DER en la imagen lo mejoran. La confusión viene de la
conversación en vivo: responder con una imagen anterior o repetir un lado ya dicho.

**Cambio (5 idiomas):** nueva tarea LADOS. Izquierda, derecha o al frente se dicen
según la imagen más reciente, no según lo dicho antes; si el objeto ya no está a la
vista, se dice en vez de repetir un lado; y si un lado anterior era otro, se corrige
en voz alta ("Corrijo: está a tu derecha").
Si la persona corrige un lado, el asistente vuelve a mirar la imagen y solo le da la
razón si la imagen lo confirma: en CP-LAZA-109 aceptó cada corrección sin mirar.
Si no reconoce con claridad el objeto que le piden, lo dice aunque le pregunten varias
veces, sin cambiarlo por otro parecido ni dar un lado al azar. En CP-LAZA-109 dijo dos
veces "no veo un piano" y a la tercera inventó "un mueble similar a un piano, a la
derecha". Con las mismas fotos en una sesión nueva respondía bien: los errores venían de
la insistencia en la conversación, no de la imagen (ni de la resolución, ni de dar las
dos opciones en la pregunta, según el spike).
Si le preguntan por algo que ya no está en la imagen, dice dónde lo vio por última vez
("Hace un momento estaba a tu izquierda; ahora no lo veo"), y si lo corrigen sobre algo
que no ve, no acepta ni niega: dice que ahora no lo ve. En la tercera prueba respondió
por una persona que ya no estaba en la imagen y aceptó la corrección sin verla.

El resto del prompt es igual al de v1.11.0.

## v1.11.0 — 2026-09-30 — Alerta SOS con ubicación y contacto de emergencia (LAZA-38 · HU-012)

**Motivo:** HU-012 pide que la persona pueda pedir ayuda humana por voz y que su
contacto de emergencia reciba la ubicación. La regla es detenerse y esperar apoyo
humano, no que el asistente improvise.

**Cambio (5 idiomas):** nuevo bloque SOS, entre los comandos y las tareas:

- "SOS", "emergencia" o "necesito ayuda" como pedido de auxilio → `trigger_sos` de
  inmediato. El asistente sigue el resultado de la app:
  - `pending`: hace la pregunta de confirmación ("¿Envío la alerta a…?"). Sí o "SOS"
    → `trigger_sos` otra vez; no → `cancel_sos`. Sin respuesta, la app la envía sola
    a los 5 s y avisa con el mensaje `[SOS]` seguido del resultado.
  - `sent`: dice que el contacto ya tiene la ubicación, le pide detenerse en un lugar
    seguro y ofrece llamar al contacto.
  - `unconfirmed`: la red no confirmó el envío a tiempo; dice que no puede
    confirmar que llegó y ofrece llamar al contacto.
  - `failed`: dice que no se envió y ofrece llamar al contacto o al 123.
  - `no_contact`: ofrece llamar al 123 y pide configurar un contacto.
- Nunca da la alerta por enviada sin `sent`, no dice en voz alta el nombre de las
  funciones y no improvisa instrucciones de rescate.
  Ante un peligro grave recuerda la línea oficial 123.
- "Mi contacto de emergencia es…" → `set_emergency_contact` (nombre y número); lo
  repite en grupos de dígitos para confirmarlo.
- Llamar al contacto o al 123 → `call_phone`.
- Cada SOS llama a `trigger_sos` aunque ya se haya enviado una alerta: la app decide
  (si se envió hace menos de 60 s, pregunta "¿Envío otra?" y no la envía sola).
- La ayuda menciona el comando "SOS".

El resto del prompt es igual al de v1.10.0.

## v1.10.0 — 2026-09-30 — Ubicación por GPS con get_location (LAZA-39 · HU-013)

**Motivo:** HU-013 pide que, a "¿dónde estoy?", el asistente use la posición si el
GPS es confiable y lo diga si no lo es (criterio 3). La posición solo se envía cuando
se pide (regla 4), para no saturar la sesión.

**Cambio (5 idiomas):** la identidad nombra la nueva función `get_location`. Si la
persona pregunta dónde está o en qué calle, la llama y responde con la calle y el
barrio junto con lo que ve. Si el resultado no es `ok` (sin permiso, sin señal o GPS
no confiable), le dice que ahora no puede saber su ubicación con seguridad. La app
responde a la función con la dirección aproximada, la precisión y el estado de
confiabilidad.

**Ajuste tras la prueba en el teléfono (2026-10-05):** bajo techo, a "¿dónde estoy?"
el asistente describió la sala sin llamar a `get_location`, porque la tarea de
describir la escena usaba la misma frase. Ahora esa tarea se pide con "¿qué hay a mi
alrededor?", y `get_location` se llama **cada vez** que la persona pregunta dónde
está, aunque ya la haya usado y aunque esté bajo techo.

El resto del prompt es igual al de v1.9.0.

## v1.9.0 — 2026-09-24 — Modo reunión y silencio total nombrados en la identidad; resumen de lo escuchado (LAZA-37 · HU-011)

**Motivo:** HU-011 depende de que el asistente llame a `set_meeting_mode` y a
`set_microphone`. Las dos funciones solo aparecían en la sección de comandos. Los
hallazgos 11 y 12 mostraron que una función que no está nombrada en la identidad
puede "aplicarse" solo de palabra. HU-011 pide además que en modo reunión pueda
resumir lo que se dijo.

**Cambio (5 idiomas):**

- Identidad: nombra `set_meeting_mode` (entrar o salir del modo reunión) y
  `set_microphone` (silencio total). Añade ambos a la lista de ajustes que no se
  pueden confirmar sin llamar a su función.
- Modo reunión: si lo llaman por su nombre y preguntan qué se dijo, resume lo
  escuchado en 2 a 4 frases.

La app añade una red de seguridad: en modo reunión retiene el audio del asistente y
solo lo deja sonar si en la transcripción aparece su nombre o si el turno entra o sale
del modo.

El resto del prompt es igual al de v1.8.0.

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
