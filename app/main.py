from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router
from app.core.config import settings
from app.sockets.live_proxy import live_proxy


def create_fastapi_app() -> FastAPI:
    app = FastAPI(
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
