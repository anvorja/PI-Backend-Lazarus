"""Conexión a la base de datos del control de acceso (HU-044 a HU-046).

SQLAlchemy síncrono: las rutas HTTP corren en el pool de hilos de FastAPI y el
proxy WebSocket llama a la base con `asyncio.to_thread`.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str) -> Engine:
    # Neon entrega URLs "postgresql://": se usa el driver psycopg 3.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=args, pool_pre_ping=True)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def reset_engine(url: str) -> None:
    """Cambia la base (pruebas)."""
    global engine
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


def init_db() -> None:
    from app.db import models  # noqa: F401 — registra las tablas

    Base.metadata.create_all(engine)
    _add_missing_columns()


# Columnas agregadas después de crear la tabla: create_all no toca las que ya existen
# (Neon ya tiene `device_sessions`), así que se agregan aquí, una sola vez.
_LATE_COLUMNS = {
    "device_sessions": {
        "carrier": "VARCHAR(40) NOT NULL DEFAULT ''",
        "transport": "VARCHAR(12) NOT NULL DEFAULT ''",
    },
}


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _LATE_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
