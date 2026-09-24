# Comandos de voz — Gemini Live (Lazarus)

Toda la personalización se hace **hablándole al asistente**; no hay menús que ver.
El asistente se llama **"Aria"** por defecto (configurable por voz; se guarda en el
teléfono hasta que se cambie de nuevo). La voz por defecto es **Charon** y el idioma, **español**.

Cómo iniciar: **toca cualquier parte de la pantalla**. Aria se presenta y empieza a
observar el entorno. Para terminar, pulsa el botón rojo de abajo.

La interfaz es **voz-first**: no hay selector de idioma ni otros menús visuales (por
accesibilidad: menos nodos focusables para el lector de pantalla y una
sola forma de hacer cada cosa). El idioma se cambia diciendo p. ej. *"habla en
inglés"* y persiste.

---

## Comandos disponibles

Cada comando se puede pedir con frases naturales (no hay que decirlas literalmente).
Los marcados como **persistente** se recuerdan entre sesiones (`SharedPreferences`
en el teléfono); los demás son conversacionales. Cada cambio se confirma en una frase corta.

| Qué hace                                 | Cómo pedirlo (ejemplos)                                                                         | Tool / persistencia                                                                                                              |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Cambiar el nombre del asistente**      | "Llámate Lazarus", "Quiero que te llames Sol", "Cámbiate el nombre a Max"                       | `set_assistant_name` · persistente (`lazarus_assistant_name`) |
| **Decir tu propio nombre**               | "Yo soy Andrés", "Me llamo Andrés"                                                              | `set_user_name` · persistente (`lazarus_user_name`) — el asistente te saluda por tu nombre al empezar cada sesión |
| **Cambiar / probar la voz**              | "Cambia tu voz a Kore", "¿Qué voces tienes?", "Prueba otra voz"                                 | `set_voice` · persistente (`lazarus_voice`) · reconecta y da una muestra corta de la nueva voz |
| **Cambiar el idioma**                    | "Habla en inglés", "Cambia a portugués", "Switch to French"                                     | `set_language` (es/en/fr/pt/it) · persistente (`lazarus_language`) · reconecta y confirma en una frase en el idioma nuevo, sin repetir la presentación |
| **Nivel de detalle**                     | "Sé más breve", "Descríbeme con más detalle"                                                    | `set_verbosity` (concise/detailed) · persistente (`lazarus_verbosity`) |
| **Pausar / reanudar descripciones**      | "Deja de describir", "Vuelve a describir"                                                       | `set_descriptions` · persistente (`lazarus_describing`) · al pausar y al reanudar confirma solo con **"Entendido."**                  |
| **Modo reunión** (escucha y recuerda, callado) | "Estoy en una reunión, escucha pero no hables", "Cállate hasta que te llame"              | `set_meeting_mode` · de sesión (no persiste) · el mic sigue abierto: oye y recuerda, pero solo responde si lo llamas **por su nombre**. Sal con "ya puedes hablar" / "salimos de la reunión" |
| **Silencio total** (privacidad)          | "Silencio total", "Mútate", "Déjame en paz"                                                     | `set_microphone` · de sesión · la app **corta el envío de mic y cámara**; se reactiva **tocando la pantalla** (no por voz). Confirma con una frase corta al reactivar |
| **Silenciar / activar avisos de la app** | "Silencia los avisos", "Quita los sonidos de la app", "Activa los avisos"                       | `set_system_cues` · persistente (`lazarus_system_cues_muted`) · calla los avisos informativos ("Asistente detenido", "Reintentando"); los que explican cómo recuperarse de un error suenan siempre |
| **Repetir lo último**                    | "Repite", "¿Qué dijiste?"                                                                       | conversacional (sin tool) · repite su última respuesta con las mismas palabras |
| **Ayuda / lista de comandos**            | "Ayuda", "¿Qué puedes hacer?", "¿Qué comandos hay?"                                             | conversacional (sin tool)                                                                                                        |

> En **pausa de descripciones**, Aria deja de narrar el entorno por su cuenta: solo
> responde preguntas y emite **siempre** las **alertas de seguridad**. La pausa persiste:
> al abrir la app de nuevo, Aria avisa al saludar que las descripciones siguen en pausa.

### Los tres grados de silencio (cuándo usar cada uno)

1. **Pausar descripciones** (`set_descriptions`): deja de narrar el entorno, pero
   **sigue respondiendo** lo que le preguntes y avisa de peligros. Útil para "no me
   estés describiendo todo el rato".
2. **Modo reunión** (`set_meeting_mode`): **calla del todo y NO responde** a lo que
   oye —aunque haya gente hablando—, pero **sigue escuchando y recordando** para que
   luego puedas pedirle "¿qué se dijo?". Solo te responde si lo llamas **por su
   nombre**. Útil en reuniones, clases o conversaciones.
3. **Silencio total** (`set_microphone`): **apaga el micrófono y la cámara** (no oye,
   no ve, no recuerda). Privacidad máxima. Se reactiva **tocando la pantalla**, no por
   voz. Útil para conversaciones privadas o ahorrar batería/datos.

### Voces disponibles

`Charon` (informativa, por defecto), `Puck` (animada), `Kore` (firme), `Fenrir`
(enérgica), `Aoede` (relajada), `Leda` (juvenil), `Orus` (grave), `Zephyr`
(brillante). Para elegir, di p. ej. *"cambia tu voz a Aoede"*; la oirás al instante
y puedes probar otras hasta quedarte con una. La **voz** (timbre) es independiente del
**nombre** del asistente: puedes llamarlo "Orion" y que suene con la voz "Kore".

---

## Tareas a petición

A diferencia de los comandos de arriba (que *cambian ajustes*), estas son tareas
**puntuales**: Aria las hace una vez y vuelve al modo normal. Son conversacionales
(no cambian nada persistente).

| Tarea                   | Cómo pedirla (ejemplos)                          | Qué hace                                                                                                                                                 |
| ----------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Leer texto**          | "¿Qué dice esto?", "Lee la etiqueta", "Lee esto" | Lee en voz alta el texto que ve la cámara, tal cual (carteles, billetes, medicinas, pantallas, menús). Si no hay texto legible, pide acercar/estabilizar |
| **Describir la escena** | "¿Dónde estoy?", "Descríbeme todo"               | Barrido completo del entorno (2-4 frases): primero riesgos, luego disposición general, luego objetos y personas                                          |
| **Buscar un objeto**    | "¿Dónde está la puerta?", "Busca una silla"      | Localiza el objeto y guía paso a paso con horas de reloj y pasos ("a las 2, dos pasos"). Si no está a la vista, sugiere girar despacio para escanear     |

---

## Cómo cambiar el nombre (de "Aria" a otro)

Estando la sesión activa, di algo como:

- *"Llámate Lazarus."*
- *"Quiero que te llames Sol."*

Aria llama a la función `set_assistant_name`, confirma en una frase corta y a partir
de ahí responde con el nuevo nombre. El cambio **persiste**: la próxima vez que abras
la app seguirá llamándose igual hasta que lo vuelvas a cambiar.

(Para volver al nombre original, basta con decir *"Llámate Aria."*)

---

## Cómo escuchar la ayuda si olvidas los comandos

Simplemente **pregúntale**, en voz alta, con la sesión activa:

- *"Ayuda."*
- *"¿Qué puedes hacer?"*
- *"¿Qué comandos hay?"*

Aria enumera en voz alta lo que puedes pedirle (leer un texto, describir dónde estás,
buscar un objeto, cambiar su nombre, cambiar el idioma, más o menos detalle,
pausar/reanudar descripciones, ponerla en modo reunión, pedir silencio total,
silenciar/activar avisos, cambiar su voz y repetir lo último) con un ejemplo de frase
para cada uno. No hace falta recordar las palabras exactas: cualquier frase parecida
funciona.

---

## Notas de implementación

- Las funciones (`set_*`) se declaran en `app/services/live_service.py`
  (`_FUNCTION_DECLARATIONS`) y se inyectan en el `setup` de la sesión.
- La guía de uso (incluida la de **ayuda** y **repetir**) vive en el system prompt:
  `app/prompts/companion.py` → `_COMMANDS_EXTRA` / `_LIVE_IDENTITY`.
- Las **tareas a petición** (leer texto / describir escena / buscar objeto) viven en
  `app/prompts/companion.py` → `_TASK_INTENTS`. Son conversacionales: Gemini ya ve la
  cámara y oye al usuario, así que las atiende sin function calling.
- La app Flutter ejecuta los `toolCall` en `LiveController._handleToolCall`
  (`lib/features/live/presentation/controllers/live_controller.dart`) y persiste con
  `LiveSettingsRepository` (`SharedPreferences`, claves `lazarus_*`). Responde a cada
  llamada con `ok` o con un error que el asistente explica (idioma o voz no
  disponibles).
- Cambiar **voz** o **idioma** exige una sesión nueva (ambos se fijan en el `setup`): la
  app responde a la función, reconecta y envía el sentinela `[VOZ]` (muestra corta de la
  voz) o `[IDIOMA]` (confirmación corta en el idioma nuevo) en lugar de `[INICIO]`.
- **Modo reunión** y **silencio total** son de **sesión** (no persisten): son estados
  de la conversación, no ajustes. El silencio total se implementa en el cliente
  (corta el envío de mic/cámara) y se sale **tocando la pantalla**; si la sesión murió
  por inactividad, el toque **reconecta** con un saludo breve (sentinel `[MIC_ON]`).
- "Repetir" y "ayuda" son **conversacionales**: el modelo responde directamente, sin
  llamar a ninguna función.
- Disponible en 5 idiomas: es, en, fr, pt, it.
