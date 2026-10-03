"""Application configuration.

Settings are read from environment variables, falling back to the repository
root ``.env`` file. Every variable is namespaced with a ``GUARDIAN_`` prefix so
backend config never collides with frontend (``VITE_``) config in the shared
``.env``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
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
        hide_input_in_errors=True,
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

    # ---- WhatsApp ----
    # Which provider adapter to use. See app.services.whatsapp.registry.
    whatsapp_provider: str = "meta"

    # Shared secret echoed back during the provider's subscription handshake.
    # Intentionally empty by default: an unset token must fail loudly rather
    # than silently accept whatever the caller sends.
    whatsapp_verify_token: str = ""

    # ---- URL verification (SerpApi) ----
    # API key for https://serpapi.com. Empty by default: live verification is
    # opt-in, and an unconfigured deployment simply skips it rather than
    # erroring. Get a key at https://serpapi.com/manage-api-key.
    serpapi_api_key: SecretStr = SecretStr("")
    serpapi_endpoint: HttpUrl = HttpUrl("https://serpapi.com/search.json")
    serpapi_timeout: float = Field(default=10.0, gt=0, le=30, allow_inf_nan=False)
    # Cap retained results from the first page; no pagination or extra searches.
    serpapi_results_per_domain: int = Field(default=5, ge=1, le=10)
    # Bound paid requests from a single message, including failed lookups.
    serpapi_max_domains: int = Field(default=5, ge=1, le=20)

    @field_validator("serpapi_endpoint")
    @classmethod
    def _secure_serpapi_endpoint(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.username or value.password or value.query or value.fragment:
            raise ValueError("SerpApi endpoint must use HTTPS without credentials, query, or fragment.")
        return value

    @property
    def url_verification_enabled(self) -> bool:
        """True when live URL verification is configured and usable."""
        return bool(self.serpapi_api_key.get_secret_value().strip())

    # ---- Gemma reasoning ----
    # Explicit opt-in: message text and collected evidence are sent to this
    # inference provider. The default model is open-weight Gemma, not Gemini.
    gemma_enabled: bool = False
    gemma_provider: Literal["openrouter", "openai_compatible"] = "openrouter"
    gemma_base_url: HttpUrl = HttpUrl("https://openrouter.ai/api/v1")
    gemma_api_key: SecretStr = SecretStr("")
    gemma_model: str = Field(default="google/gemma-3-27b-it", min_length=1, max_length=200)
    gemma_timeout: float = Field(default=30.0, gt=0, le=120, allow_inf_nan=False)
    gemma_max_tokens: int = Field(default=1024, ge=128, le=4096)
    gemma_max_input_chars: int = Field(default=60_000, ge=4096, le=200_000)
    gemma_response_format: Literal["json_schema", "json_object"] = "json_schema"

    @field_validator("gemma_model")
    @classmethod
    def _gemma_model_name(cls, value: str) -> str:
        value = value.strip()
        if "gemma" not in value.lower() or any(char.isspace() for char in value):
            raise ValueError("Configure a Gemma model ID or a served alias containing 'gemma'.")
        return value

    @field_validator("gemma_base_url")
    @classmethod
    def _secure_gemma_base_url(cls, value: HttpUrl) -> HttpUrl:
        loopback = value.host in {"localhost", "127.0.0.1", "[::1]", "::1"}
        if value.scheme != "https" and not loopback:
            raise ValueError("Gemma requires HTTPS, except for a loopback inference server.")
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("Gemma base URL must not contain credentials, query, or fragment.")
        return value

    @model_validator(mode="after")
    def _gemma_configuration(self) -> Self:
        if self.gemma_enabled:
            loopback = self.gemma_base_url.host in {"localhost", "127.0.0.1", "[::1]", "::1"}
            if not loopback and not self.gemma_api_key.get_secret_value().strip():
                raise ValueError("GUARDIAN_GEMMA_API_KEY is required for remote Gemma inference.")
            if self.gemma_provider == "openrouter" and self.gemma_base_url.host != "openrouter.ai":
                raise ValueError("Use the openai_compatible provider for a non-OpenRouter Gemma endpoint.")
        return self

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
