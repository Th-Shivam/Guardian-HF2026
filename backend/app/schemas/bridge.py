"""Transport constraints for normalized messages from the Baileys bridge."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.services.processing.models import GuardianMessage


class BridgeMessage(GuardianMessage):
    """Reuse Guardian's message contract, bounded for private WhatsApp chats."""

    message_id: str = Field(min_length=1, max_length=200)
    sender_id: str = Field(
        max_length=200,
        pattern=r"^\d+(?::\d+)?@(s\.whatsapp\.net|lid)$",
    )
    text: str = Field(min_length=1, max_length=4096)
    received_at: AwareDatetime
    source: Literal["whatsapp"]


class BridgeReply(BaseModel):
    """Only the reply needed by the transport, not private analysis evidence."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    reply: str = Field(min_length=1, max_length=2000)
