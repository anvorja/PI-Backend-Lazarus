from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router
from app.core.config import settings
from app.core.telemetry import configure_telemetry_logging
from app.db.session import SessionLocal, init_db
from app.services.admin_auth import bootstrap_admin
from app.sockets.live_proxy import live_proxy


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Tablas del control de acceso y primer administrador del panel (HU-044/046).
    init_db()
    with SessionLocal() as db:
        bootstrap_admin(db)
    yield


def create_fastapi_app() -> FastAPI:
    configure_telemetry_logging()
    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-powered backend for Lazarus — accessibility app for people "
            "with visual impairment. Real-time assistance via the Gemini Live API "
            "(native audio) over a WebSocket proxy."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    # Proxy WebSocket de Gemini Live (audio nativo): la app móvil habla con este
    # endpoint y el backend reenvía a Gemini con la API key server-side.
    app.add_api_websocket_route("/ws/live", live_proxy)

    return app


app = create_fastapi_app()
