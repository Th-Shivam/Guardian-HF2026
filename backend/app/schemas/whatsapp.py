"""Provider-agnostic WhatsApp schemas.

Nothing here is specific to Meta. Provider adapters translate their own wire
format into these models, so the rest of Guardian only ever sees
``InboundMessage``.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class VerificationRequest(BaseModel):
    """Subscription handshake parameters sent by a provider."""

    mode: str = Field(examples=["subscribe"])
    token: str = Field(examples=["my-verify-token"])
    challenge: str = Field(examples=["1158201444"])


class InboundMessage(BaseModel):
    """A single text message a user forwarded to Guardian."""

    message_id: str = Field(examples=["wamid.HBgLMTY1MDUwNTEyMzQVAgARGBI5QTNDQTVCM0Q0Q0Q2RTY3Q0IA"])
    sender: str = Field(description="Sender's phone number in E.164 form, no '+'.", examples=["16505551234"])
    sender_name: str | None = Field(default=None, examples=["Asha"])
    text: str = Field(description="Raw message body, unmodified.")
    timestamp: datetime = Field(description="When the provider received the message (UTC).")


class ParsedWebhook(BaseModel):
    """Result of normalising one webhook delivery."""

    messages: list[InboundMessage] = Field(default_factory=list)
    ignored: int = Field(
        default=0,
        description=(
            "Events received but not turned into messages: delivery statuses, "
            "non-text message types, and changes for other subscription fields."
        ),
    )


class AcknowledgedMessage(BaseModel):
    """One accepted message, echoed back to the caller.

    Deliberately omits the message body. Guardian handles content people
    believe may be malicious; there is no reason to reflect it into the
    provider's logs.
    """

    message_id: str
    sender: str
    timestamp: datetime


class WebhookAck(BaseModel):
    """Structured acknowledgement for a webhook delivery."""

    status: str = Field(default="received", examples=["received"])
    provider: str = Field(examples=["meta"])
    accepted: int = Field(description="Number of text messages extracted.")
    ignored: int = Field(description="Number of events deliberately skipped.")
    messages: list[AcknowledgedMessage] = Field(default_factory=list)
