# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/). Cada versión corresponde a una
release del Release Plan de Lazarus.

## [Sin publicar] · Sprint 3

### Agregado
- Alertas de consumo para el panel (HU-051, LAZA-124):
  - `GET /api/v1/admin/usage` da la transferencia del mes frente al límite del plan de
    Render, los minutos de Live frente al presupuesto y la última falla de Gemini por
    facturación o cuota;
  - `POST /api/v1/admin/usage/check` prueba la conexión con Gemini sin gastar minutos;
  - límites configurables desde el panel (`usage_limits`), con aviso desde el 80 %.
- Notas ligadas a la ruta (HU-050, LAZA-123): el teléfono puede subir `notas_ruta.csv` con
  la ruta y el punto siguiente de cada nota; `/admin/devices/{id}/notes` los une a la nota
  junto con su revisión, y `PUT /admin/devices/{id}/notes/review` la marca aplicada,
  descartada o pendiente.
- ADR 0001 a 0003 y documentos de arquitectura en `docs/architecture`.

### Cambiado
- Prompt v1.31.0: en un cruce con el semáforo apagado o dudoso dice que no ve ninguna luz,
  no confirma "¿puedo cruzar?" y ante un bloqueo ofrece el SOS (HU-020, LAZA-48); con una
  ruta activa y el GPS perdido lo avisa y no afirma en qué punto va (HU-021, LAZA-49).
- Prompt v1.32.0: en los cruces distingue el semáforo peatonal del vehicular, advierte el
  giro a la derecha en rojo, trata la cebra como cruce sin control, habla lo mínimo mientras
  la persona cruza y no confirma la llegada (HU-020, estado del arte); sin GPS, da una estimación con `get_route_progress` (pasos contados y
  brújula) y a los 3 minutos ofrece ayuda o el SOS (HU-021, fase 2).
- Prompt v1.30.0: con una ruta activa, el asistente no dice "no puedo guiarte" ni lee
  "[RUTA]" (LAZA-126).
- Las pruebas no dependen del `.env` local.

## [0.2.0] — 2026-10-29 · R1: piloto técnico listo para campo

Primera versión del backend usada en campo con un usuario real: prueba diurna controlada
entre la estación Buitrera del MIO y la entrada de la Universidad del Valle (27 y 28 de
octubre, sin incidentes).

### Núcleo conversacional
- Proxy WebSocket seguro hacia Gemini Live: la clave del servicio de IA vive solo en el
  servidor (HU-001, ADR-0003).
- Configuración del modelo, voz e idioma, con duración máxima de sesión (HU-002).
- Prompt de sistema versionado (HU-003), de v1.1.0 a **v1.29.0**, entre otros con:
  - regla de cruces: el asistente nunca autoriza cruzar;
  - lateralidad confiable;
  - alertas proactivas;
  - modo reunión y silencio total;
  - SOS;
  - regla horaria de Unicentro;
  - TalkBack;
  - ruta curada;
  - notas de campo;
  - observación sin repetir objetos.
- Funciones del asistente: ubicación (`get_location`), hora local del teléfono
  (`get_time`), brújula (`get_heading`), notas de campo (`add_note`) y rutas curadas.

### Piloto y operación
- Pausa del servicio desde el servidor (`LIVE_ENABLED`, HU-043).
- Registro y aprobación de teléfonos, con horario y límite de minutos (HU-044).
- Logs de campo por teléfono en el servidor, sin números de teléfono (HU-045).
- API del panel de administración en `/api/v1/admin` (HU-046).
- Perfiles de ruta curados en la base de datos, con notas de campo y recorrido GPS por
  teléfono para el editor de rutas (HU-022).
- Métricas de capacidad, operador de red por sesión y script de carga (HU-047).

### Entrega
- Integración continua: ruff, pytest (325 pruebas) y build de la imagen con prueba de
  humo.
- La imagen probada se publica en Docker Hub (`develop`, `latest`, `vX.Y.Z` y short SHA)
  y corre en Render con Postgres en Neon (ADR-0006).
- `/api/v1/health` informa la versión 0.2.0.

[0.2.0]: https://github.com/anvorja/PI-Backend-Lazarus/releases/tag/v0.2.0
