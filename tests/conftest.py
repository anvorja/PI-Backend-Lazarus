"""Configuración común de pruebas: variables de entorno mínimas y sin secretos."""

import os

os.environ.setdefault("GEMINI_API_KEY", "clave-de-prueba")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost"]')

# El `.env` local (el de desarrollo, con la aprobación de teléfonos activa y
# las credenciales del panel) no debe cambiar las pruebas: las variables de
# entorno tienen prioridad sobre el archivo. Sin esto, con un `.env` local
# fallaban 31 pruebas que en la CI (sin `.env`) pasan.
os.environ["DEVICE_AUTH_REQUIRED"] = "false"
os.environ["ADMIN_USERNAME"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["PLATFORM"] = "local"
os.environ["DEBUG"] = "false"
os.environ["GEMINI_LIVE_LANGUAGE"] = "es"

# Base de datos de pruebas: SQLite en un archivo temporal, nunca la de Render.
import tempfile  # noqa: E402

_DB_DIR = tempfile.mkdtemp(prefix="lazarus-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_DIR}/pruebas.db"
os.environ.setdefault("ADMIN_JWT_SECRET", "secreto-de-prueba-de-al-menos-32-caracteres")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """Cada prueba con las tablas vacías."""
    from app.db.session import Base, engine, init_db
    from app.services import access

    init_db()
    yield
    Base.metadata.drop_all(engine)
    access._admin_closed_at.clear()
