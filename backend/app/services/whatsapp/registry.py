"""Provider selection.

Swapping messaging backends is a config change (``GUARDIAN_WHATSAPP_PROVIDER``),
not a code change. Register new adapters in ``PROVIDERS``.
"""

from fastapi import Depends

from app.config import Settings, get_settings
from app.services.whatsapp.base import WhatsAppProvider
from app.services.whatsapp.errors import ConfigurationError
from app.services.whatsapp.meta import MetaCloudProvider

PROVIDERS: dict[str, type[WhatsAppProvider]] = {
    MetaCloudProvider.name: MetaCloudProvider,
}


def build_provider(settings: Settings) -> WhatsAppProvider:
    """Instantiate the configured provider adapter."""
    key = settings.whatsapp_provider.strip().lower()
    try:
        provider_cls = PROVIDERS[key]
    except KeyError as exc:
        raise ConfigurationError(
            f"Unknown WhatsApp provider {settings.whatsapp_provider!r}. "
            f"Available: {', '.join(sorted(PROVIDERS))}."
        ) from exc
    return provider_cls(verify_token=settings.whatsapp_verify_token)


def get_whatsapp_provider(settings: Settings = Depends(get_settings)) -> WhatsAppProvider:
    """FastAPI dependency yielding the configured provider."""
    return build_provider(settings)
