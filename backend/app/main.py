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
from app.services.processing import MessageProcessor
from app.services.url import SerpApiClient, UrlVerifier

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the shared SerpApi connection pool and the message pipeline."""
    settings: Settings = app.state.settings
    logger.info("Guardian API starting (env=%s, debug=%s)", settings.env, settings.debug)
    serpapi_client: SerpApiClient | None = None
    try:
        verifier = None
        if settings.url_verification_enabled:
            serpapi_client = SerpApiClient(
                settings.serpapi_api_key.get_secret_value(),
                endpoint=str(settings.serpapi_endpoint),
                timeout=settings.serpapi_timeout,
            )
            verifier = UrlVerifier(
                serpapi_client,
                results_per_domain=settings.serpapi_results_per_domain,
                max_domains=settings.serpapi_max_domains,
            )
        app.state.message_processor = MessageProcessor(url_verifier=verifier)
        logger.info("Live URL verification %s", "enabled" if verifier else "disabled")
        yield
    finally:
        if serpapi_client is not None:
            serpapi_client.close()
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
