"""Guardian's internal message pipeline.

The transport-independent core of the product. A transport (today the WhatsApp
webhook) normalises its payload into a :class:`GuardianMessage` and hands it to
:class:`MessageProcessor`; neither this package nor its model knows about
WhatsApp, Meta, or FastAPI.

Flow::

    provider payload -> GuardianMessage -> MessageProcessor -> ProcessedMessage

``process_with_analysis`` returns the normalized message, its existing analysis,
and a structured Gemma risk assessment when configured and available. Missing
or failed reasoning is explicit, never a fake assessment. ``process`` keeps the
original message-only return value.

Keeping the model here rather than in ``app.schemas`` is what preserves the
dependency direction: transports depend on the domain, never the other way
round.
"""

from app.services.processing.errors import InvalidMessageError, ProcessingError
from app.services.processing.models import GuardianMessage
from app.services.processing.service import MessageProcessor, ProcessedMessage

__all__ = [
    "GuardianMessage",
    "InvalidMessageError",
    "MessageProcessor",
    "ProcessedMessage",
    "ProcessingError",
]
