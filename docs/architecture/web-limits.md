# Límites del navegador — evidencias que justifican Flutter

> **Documento vivo.** Se va llenando con cada limitación concreta que encontremos al
> usar el cliente web en condiciones reales. Su objetivo es **sustentar con hechos** la
> decisión de migrar a Flutter (ver `lazarus-plan.md` y ADR
> `decisions/0003-ephemeral-tokens-vs-proxy.md`), no teorizar.
>
> Regla: una evidencia no cuenta hasta que esté **reproducida y anotada** aquí con su
> contexto (dispositivo, navegador, qué pasó, impacto para una persona ciega).

---

## Resumen ejecutivo

| # | Limitación | Severidad | ¿Flutter lo resuelve? | Estado |
|---|---|---|---|---|
| 1 | Pantalla bloqueada corta cámara/micrófono/WebSocket | 🔴 Crítica | Sí (background services) | ⬜ por documentar |
| 2 | GPS en segundo plano impreciso/suspendido | 🔴 Crítica | Sí (`geolocator` background) | ⬜ por documentar |
| 3 | Sin brújula/acelerómetro fiables → no hay "reloj real" | 🟠 Alta | Sí (`flutter_compass` + `sensors_plus`) | ⬜ por documentar |
| 4 | Consumo de batería elevado con cámara+WS continuos | 🟠 Alta | Parcial (FPS adaptativo nativo) | ⬜ por documentar |
| 5 | Integración limitada con lector de pantalla (TalkBack/VoiceOver) | 🟡 Media | Sí (APIs nativas de accesibilidad) | ⬜ por documentar |
| 6 | Sin acceso a botón de auriculares Bluetooth | 🟡 Media | Sí (eventos de media nativos) | ⬜ por documentar |
| 7 | Cancelación de ruido del micrófono limitada | 🟡 Media | Sí (audio nativo / DSP) | ⬜ por documentar |

> Objetivo del plan: **≥ 5 evidencias concretas** antes de dar por cerrada la
> justificación de Flutter. (Varias ya son conocidas a priori; aquí se documenta la
> evidencia reproducida, no la suposición.)

---

## Evidencias detalladas

### 1. Pantalla bloqueada corta la sesión

- **Síntoma esperado:** al bloquear el teléfono o cambiar de app, el navegador suspende
  `getUserMedia` (cámara/micrófono) y deja caer el WebSocket → el asistente deja de ver,
  oír y responder.
- **Impacto para persona ciega:** rompe el caso de uso central (caminar con el teléfono
  en el bolsillo o la mano sin mirar la pantalla). Inutilizable en movilidad real.
- **Reproducción:** _(pendiente: dispositivo, navegador, pasos, qué se observó)_
- **Flutter:** `flutter_background_service` mantiene la captura y la sesión activas con
  pantalla bloqueada.

### 2. GPS en segundo plano

- **Síntoma esperado:** `navigator.geolocation.watchPosition` se degrada o se suspende
  cuando la pestaña no está en primer plano; precisión insuficiente para orientación a
  pie.
- **Impacto:** sin ubicación fiable no hay contexto de exteriores (Places, cruces,
  negocios cercanos).
- **Reproducción:** _(pendiente)_
- **Flutter:** `geolocator` con permisos de ubicación en segundo plano + geofencing.

### 3. Sin "sistema del reloj" absoluto

- **Síntoma esperado:** el navegador no expone brújula/orientación de forma fiable y
  consistente entre dispositivos; "a tus 3 en punto" no puede anclarse a una dirección
  física real.
- **Impacto:** la orientación tipo reloj queda relativa a la cámara, no al cuerpo del
  usuario → menos útil para navegar.
- **Reproducción:** _(pendiente)_
- **Flutter:** `flutter_compass` + `sensors_plus` permiten convertir la dirección
  relativa en absoluta según la orientación física del teléfono.

### 4. Batería

- **Síntoma esperado:** cámara + WebSocket + audio continuo agotan la batería rápido; el
  navegador no permite ajustar el pipeline a bajo nivel.
- **Impacto:** autonomía insuficiente para uso diario.
- **Reproducción:** _(pendiente: medir % batería/hora en un dispositivo de referencia)_
- **Flutter:** FPS adaptativo nativo (1 FPS caminando, más quieto interactuando) y mejor
  control del ciclo de vida.

### 5. Lector de pantalla

- **Síntoma esperado:** la integración web con TalkBack/VoiceOver es limitada frente a
  las APIs de accesibilidad nativas (gestos, foco, anuncios).
- **Impacto:** fricción en el onboarding y control para usuarios que dependen del lector.
- **Reproducción:** _(pendiente)_
- **Flutter:** APIs de accesibilidad nativas integradas.

### 6. Botón de auriculares Bluetooth

- **Síntoma esperado:** el navegador no da acceso fiable al botón físico del auricular
  como disparador ("pulsar = hablar con el asistente").
- **Impacto:** falta un gesto discreto y manos libres para activar la interacción.
- **Reproducción:** _(pendiente)_
- **Flutter:** eventos de control de media nativos.

### 7. Cancelación de ruido

- **Síntoma esperado:** poco control sobre el preprocesado del micrófono en calle/ruido.
- **Impacto:** transcripción/comprensión degradada en exteriores.
- **Reproducción:** _(pendiente)_
- **Flutter:** procesamiento de audio nativo / DSP antes de enviar a Gemini.

---

## Plantilla para nuevas evidencias

```
### N. <título corto>

- **Síntoma:** <qué falla, observado>
- **Impacto para persona ciega:** <por qué importa>
- **Reproducción:** dispositivo <...>, navegador <...>, pasos <...>, resultado <...>
- **Flutter:** <cómo lo resuelve el cliente nativo>
- **Severidad:** 🔴/🟠/🟡
```
