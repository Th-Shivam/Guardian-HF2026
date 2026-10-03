"""Translation from a WhatsApp message into Guardian's internal model.

Lives in the transport package, not in ``app.services.processing``, because the
dependency runs one way: transport knows about the domain, never the reverse.
Guardian's core must stay usable by a transport that has never heard of
WhatsApp.
"""

from app.schemas.whatsapp import InboundMessage
from app.services.processing import GuardianMessage

#: Channel recorded on every message that arrives over WhatsApp. This is the
#: product the person used, not the vendor (``MetaCloudProvider.name`` is
#: "meta" — one of several possible Cloud API vendors).
SOURCE_WHATSAPP = "whatsapp"


def to_guardian_message(message: InboundMessage) -> GuardianMessage:
    """Normalise one inbound WhatsApp message into Guardian's internal shape."""
    return GuardianMessage(
        message_id=message.message_id,
        sender_id=message.sender,
        text=message.text,
        received_at=message.timestamp,
        source=SOURCE_WHATSAPP,
    )
