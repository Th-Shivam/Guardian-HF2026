"""The internal message-processing service.

Everything that arrives from any transport funnels through here before it is
analysed, stored, or answered. Today it validates and normalises and logs that
a message was received; analysis, URL checks and replies are composed onto this
seam later.

Deliberately independent of WhatsApp and FastAPI: this module imports neither,
so it can be exercised on its own and driven by anything.
"""

from __future__ import annotations

from datetime import timezone
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.services.processing.errors import InvalidMessageError
from app.services.processing.models import GuardianMessage

if TYPE_CHECKING:  # annotation only; the real import happens lazily below
    from app.services.analysis import SignalAnalyzer

logger = get_logger(__name__)


class MessageProcessor:
    """Validates and normalises inbound messages, then runs signal analysis.

    Stateless today. As the pipeline grows this is where the AI client, the URL
    scanner and the evidence store get wired in, which is why callers depend on
    the class rather than on the individual steps.
    """

    def __init__(self, analyzer: SignalAnalyzer | None = None) -> None:
        # Imported here, not at module scope: the analysis package imports this
        # one, so a top-level import would close the loop and fail at startup.
        from app.services.analysis import SignalAnalyzer

        self._analyzer = analyzer or SignalAnalyzer()

    def process(self, message: GuardianMessage) -> GuardianMessage:
        """Validate, normalise, and analyse one inbound message.

        Args:
            message: A structurally valid message, as produced by a provider
                adapter.

        Returns:
            The same message with normalised text and a UTC timestamp.

        Raises:
            InvalidMessageError: the message broke a business rule — an empty
                body, or a timestamp with no timezone to trust.
        """
        normalized = self._normalize(message)

        result = self._analyzer.analyze(normalized)

        # Log identifiers, provenance, and a signal summary only. The body and
        # the URLs are content a user may believe is malicious; there is no
        # reason to copy them into our logs. No verdict is reached yet.
        logger.info(
            "Guardian received message %s from %s via %s: %d URL(s), signals=[%s]",
            normalized.message_id,
            normalized.sender_id,
            normalized.source,
            len(result.urls),
            ", ".join(signal.type.value for signal in result.signals),
        )
        return normalized

    @staticmethod
    def _normalize(message: GuardianMessage) -> GuardianMessage:
        """Apply the pipeline's normalization rules or raise."""
        text = message.text.strip()
        if not text:
            raise InvalidMessageError(
                f"Message {message.message_id!r} has an empty body; nothing to process."
            )

        received_at = message.received_at
        if received_at.tzinfo is None:
            # Guessing a timezone would silently corrupt the audit trail later.
            raise InvalidMessageError(
                f"Message {message.message_id!r} has a naive timestamp; refusing to guess a timezone."
            )

        return message.model_copy(
            update={"text": text, "received_at": received_at.astimezone(timezone.utc)}
        )
