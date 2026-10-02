"""Application configuration.

Settings are read from environment variables, falling back to the repository
root ``.env`` file. Every variable is namespaced with a ``GUARDIAN_`` prefix so
backend config never collides with frontend (``VITE_``) config in the shared
``.env``.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> <repo root>
ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    """Runtime configuration for the Guardian API."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="GUARDIAN_",
        case_sensitive=False,
        extra="ignore",
    )

    project_name: str = "Guardian"
    description: str = "WhatsApp-first AI safety assistant."
    version: str = "0.1.0"

    env: str = "development"
    debug: bool = False

    host: str = "127.0.0.1"
    port: int = 8000

    # Stored as a raw string rather than a list: pydantic-settings tries to
    # JSON-decode env vars for complex field types, which makes the friendlier
    # comma-separated form fail. Parsed via `cors_origin_list` below.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    """Return cached settings, suitable for use as a FastAPI dependency."""
    return Settings()
