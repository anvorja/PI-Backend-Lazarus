# ADR 0002 — Cliente móvil: Flutter vs. React Native vs. seguir en web (PWA)

- **Estado:** Aceptado (provisional) — 2026-06-06 · _ejecución en Fase F1_
- **Decide:** equipo Lazarus
- **Afecta a:** cliente de producción, capacidades móvil-nativas, esfuerzo de desarrollo
- **Relacionado:** `lazarus-plan.md`, `docs/architecture/web-limits.md`, `propuesta-gemini-live.pdf`,
  ADR `0003-ephemeral-tokens-vs-proxy.md`

---

## Contexto

El cliente web actual (React 19 + Vite) validó con éxito el núcleo conversacional sobre
Gemini Live (ver ADR 0001): streaming interrumpible, personalización por voz, prompts en
5 idiomas. Pero las capacidades que faltan para un producto real **no se pueden lograr en
el navegador por diseño** (ver `docs/architecture/web-limits.md`):

- Cámara/micrófono/WebSocket se **suspenden con la pantalla bloqueada** o la app en
  segundo plano → inutilizable caminando con el teléfono en el bolsillo.
- **GPS en segundo plano** impreciso o suspendido → sin contexto fiable de exteriores.
- **Sin brújula/acelerómetro fiables** → no hay "sistema del reloj" absoluto anclado a la
  orientación física del usuario.
- Integración limitada con **TalkBack/VoiceOver**, sin acceso al **botón de auriculares
  Bluetooth**, control pobre de **batería** y **cancelación de ruido**.

La condición del plan para saltar a un cliente nativo está cumplida (núcleo estable +
límites del navegador identificados). Falta elegir **con qué framework** construir el
cliente móvil. Opciones: **Flutter**, **React Native**, o seguir en **web/PWA**.

---

## Decisión

**Construir el cliente de producción en Flutter** (Fase F1 del plan). El cliente web se
conserva como **demo de escritorio**, no se reescribe.

---

## Justificación

| Criterio | Web / PWA | React Native | Flutter (elegido) |
|---|---|---|---|
| Background con pantalla bloqueada | ❌ se suspende | ✅ servicios nativos | ✅ `flutter_background_service` |
| GPS continuo / geofencing | ❌ limitado | ✅ | ✅ `geolocator` |
| Brújula + acelerómetro (reloj real) | ❌ inconsistente | ✅ | ✅ `flutter_compass` + `sensors_plus` |
| Audio nativo de baja latencia + DSP | ➖ Web Audio | ✅ | ✅ `flutter_sound` + `audio_session` |
| Accesibilidad nativa (TalkBack/VoiceOver) | ➖ parcial | ✅ | ✅ |
| Rendimiento de render | ➖ | ➖ puente JS | ✅ compila a nativo, UI consistente |
| Reuso del backend/prompts actuales | ✅ | ✅ (WebSocket igual) | ✅ (WebSocket igual) |
| Curva para un dev de TS/React | ✅ ninguna | ✅ baja (JS/React) | ➖ Dart nuevo (~1 sem onboarding) |
| Ecosistema Google (Gemini, Places, Maps) | ➖ | ➖ | ✅ SDKs first-party |

**Por qué no seguir en web/PWA:** es justamente lo que `web-limits.md` descarta — las
funciones críticas (background, GPS, sensores) no existen o son inestables en el
navegador. La web sigue siendo útil como demo, no como producto.

**Por qué Flutter sobre React Native:**

- **Ecosistema Google de primera mano**: SDKs oficiales para Gemini, Maps y Places; el
  proyecto ya está todo apoyado en Google (Gemini Live) — menos fricción de integración.
- **Rendimiento y consistencia de UI**: compila a código nativo sin el puente JS de RN;
  comportamiento idéntico entre Android/iOS, importante para una UX de accesibilidad
  predecible.
- **Sensores y audio nativos maduros** (`sensors_plus`, `flutter_compass`,
  `flutter_sound`, `audio_session`) — directamente lo que el "sistema del reloj" real y
  el pipeline de audio necesitan.
- El `propuesta-gemini-live.pdf` recomendaba explícitamente Flutter.

**Costo asumido:** la curva de Dart/Flutter para un equipo de TS/React (estimado ~1
semana de onboarding antes de F1). Se considera aceptable frente a las ventajas; React
Native ahorraría esa curva pero pierde en ecosistema Google y rendimiento.

---

## Consecuencias

**Positivas:**

- Desbloquea las capacidades móvil-nativas de la Fase F2 (background, GPS, reloj real,
  FPS adaptativo, Bluetooth, cancelación de ruido).
- **Reusa el backend y los prompts actuales sin cambios**: el cliente Flutter habla con
  el mismo `/ws/live` (ver ADR 0003, Opción A durante F1).
- SDKs Google first-party para las integraciones futuras (Places, Maps, tokens efímeros).

**Negativas / a vigilar:**

- **Curva de aprendizaje de Dart** (~1 semana de onboarding planificada).
- **Dos clientes a mantener temporalmente** (web demo + Flutter) hasta que la web se
  declare legacy (Fase F4).
- Dependencia adicional del ecosistema Google (coherente con ADR 0001).

**Ejecución:** pendiente — se realiza en Fase F1 (`lazarus-plan.md`).

---

## Alternativas descartadas

- **Web / PWA como producto** — descartada: límites insalvables del navegador
  (`web-limits.md`). Se conserva solo como demo de escritorio.
- **React Native** — descartada: válida técnicamente y con menor curva, pero pierde
  frente a Flutter en integración con el ecosistema Google, rendimiento nativo y madurez
  de los plugins de sensores/audio que este caso de uso necesita.
- **Nativo puro (Kotlin + Swift, dos bases de código)** — descartada: duplica el esfuerzo
  de desarrollo y mantenimiento sin beneficio que lo justifique para el tamaño del equipo.
