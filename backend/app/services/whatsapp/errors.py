"""Domain errors for the WhatsApp layer.

These are transport-agnostic on purpose: services raise them, and
``app.api.exception_handlers`` is the single place that decides which HTTP
status each one maps to.
"""


class WhatsAppError(Exception):
    """Base class for every WhatsApp failure. Maps to HTTP 500."""


class ConfigurationError(WhatsAppError):
    """The provider is missing configuration it cannot run without."""


class VerificationError(WhatsAppError):
    """A subscription handshake failed. Maps to HTTP 403."""


class PayloadError(WhatsAppError):
    """An inbound payload did not match the provider's schema. Maps to 422."""
