"""Top-level API router.

Future routers (analysis, evidence) get mounted here so ``main.py`` never
needs to change as the surface area grows.
"""

from fastapi import APIRouter

from app.api.routes import health, whatsapp

api_router = APIRouter()
api_router.include_router(health.router, tags=["meta"])
api_router.include_router(whatsapp.router, prefix="/api/whatsapp", tags=["whatsapp"])
