"""Domain error to HTTP status mapping.

Keeping this in one place means services can raise meaningful exceptions
without importing anything from FastAPI, and routes need no try/except.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.core.sentry import capture_exception
from app.services.whatsapp.errors import (
    ConfigurationError,
    PayloadError,
    VerificationError,
    WhatsAppError,
)

logger = get_logger(__name__)


async def handle_payload_error(_: Request, exc: PayloadError) -> JSONResponse:
    """Malformed inbound payload."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def handle_verification_error(_: Request, exc: VerificationError) -> JSONResponse:
    """Failed subscription handshake."""
    logger.warning("WhatsApp verification rejected: %s", exc)
    return JSONResponse(status_code=403, content={"detail": str(exc)})


async def handle_configuration_error(_: Request, exc: ConfigurationError) -> JSONResponse:
    """Operator error. Detail is logged, never returned."""
    capture_exception(exc)
    logger.error("WhatsApp misconfiguration: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "WhatsApp provider is misconfigured."})


async def handle_whatsapp_error(_: Request, exc: WhatsAppError) -> JSONResponse:
    """Catch-all for the WhatsApp layer."""
    capture_exception(exc)
    logger.exception("Unhandled WhatsApp error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "WhatsApp request failed."})


def register_exception_handlers(app: FastAPI) -> None:
    """Attach domain error handlers.

    Starlette resolves handlers by walking the exception's MRO, so the
    specific subclasses win over the ``WhatsAppError`` catch-all.
    """
    app.add_exception_handler(PayloadError, handle_payload_error)  # type: ignore[arg-type]
    app.add_exception_handler(VerificationError, handle_verification_error)  # type: ignore[arg-type]
    app.add_exception_handler(ConfigurationError, handle_configuration_error)  # type: ignore[arg-type]
    app.add_exception_handler(WhatsAppError, handle_whatsapp_error)  # type: ignore[arg-type]
