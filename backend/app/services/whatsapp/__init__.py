"""WhatsApp transport.

Responsibilities:
  - verify a provider's webhook subscription handshake
  - normalise inbound provider payloads into ``InboundMessage``
  - (later) send replies back to the user

Routes depend on :class:`WhatsAppProvider`, never on a concrete adapter, so
Meta's Cloud API can be swapped or joined by another backend without the HTTP
layer changing.
"""

from app.services.whatsapp.base import WhatsAppProvider
from app.services.whatsapp.errors import (
    ConfigurationError,
    PayloadError,
    VerificationError,
    WhatsAppError,
)
from app.services.whatsapp.meta import MetaCloudProvider
from app.services.whatsapp.registry import PROVIDERS, build_provider, get_whatsapp_provider

__all__ = [
    "PROVIDERS",
    "ConfigurationError",
    "MetaCloudProvider",
    "PayloadError",
    "VerificationError",
    "WhatsAppError",
    "WhatsAppProvider",
    "build_provider",
    "get_whatsapp_provider",
]
