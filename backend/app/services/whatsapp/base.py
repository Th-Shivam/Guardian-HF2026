"""The provider contract.

Any messaging backend Guardian supports implements this interface. Routes
depend on the abstract type only, so adding a provider never means touching
the HTTP layer.

Adapters must accept ``verify_token`` as a keyword argument so the registry
can construct any of them uniformly.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

from app.schemas.whatsapp import ParsedWebhook, VerificationRequest


class WhatsAppProvider(ABC):
    """Abstract transport for inbound and outbound WhatsApp messages."""

    #: Registry key, e.g. ``"meta"``.
    name: ClassVar[str]

    @abstractmethod
    def verify_subscription(self, request: VerificationRequest) -> str:
        """Validate a subscription handshake.

        Returns the challenge string to echo back verbatim.

        Raises:
            VerificationError: the mode or token was not acceptable.
            ConfigurationError: no verify token is configured.
        """

    @abstractmethod
    def parse_inbound(self, payload: Mapping[str, Any]) -> ParsedWebhook:
        """Normalise a raw webhook body into provider-agnostic messages.

        Raises:
            PayloadError: the payload did not match the provider's schema.
        """

    @abstractmethod
    async def send_text(self, to: str, body: str) -> str:
        """Send an outbound text message and return the provider message id."""
