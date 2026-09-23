"""Configuración común de pruebas: variables de entorno mínimas y sin secretos."""

import os

os.environ.setdefault("GEMINI_API_KEY", "clave-de-prueba")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost"]')
