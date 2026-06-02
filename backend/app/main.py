from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description="JARVIS AI OS Phase 1 control-plane API scaffold.",
        docs_url="/docs" if app_settings.enable_docs else None,
        redoc_url="/redoc" if app_settings.enable_docs else None,
        openapi_url="/openapi.json" if app_settings.enable_docs else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=app_settings.api_v1_prefix)

    return app


app = create_app()
