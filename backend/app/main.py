"""FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --reload --app-dir backend
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.router import api_router
from app.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks.

    Future services (DB pools, HTTP clients, model clients) should be created
    here and attached to ``app.state`` so they are shared and cleanly closed.
    """
    settings: Settings = app.state.settings
    logger.info("Guardian API starting (env=%s, debug=%s)", settings.env, settings.debug)
    yield
    logger.info("Guardian API shutting down")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI instance.

    Exposed as a factory so tests can construct an app with overridden
    settings instead of depending on process-wide environment state.
    """
    settings = settings or get_settings()
    configure_logging(debug=settings.debug)

    app = FastAPI(
        title=settings.project_name,
        description=settings.description,
        version=settings.version,
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
