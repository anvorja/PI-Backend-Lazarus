"""Configuración común de pruebas: variables de entorno mínimas y sin secretos."""

import os

os.environ.setdefault("GEMINI_API_KEY", "clave-de-prueba")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost"]')

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

    init_db()
    yield
    Base.metadata.drop_all(engine)
