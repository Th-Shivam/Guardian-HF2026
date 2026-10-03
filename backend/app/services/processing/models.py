"""Guardian's internal message model.

The single representation of an inbound message once it is inside Guardian.
Deliberately provider-independent: nothing here knows about WhatsApp, Meta, or
HTTP. Provider adapters translate their own wire format into this model, so
every downstream service — analysis, URL checks, evidence — sees one shape.

The model owns *structural* validation (required fields, types, no surprises).
Semantic rules and normalisation live in the processor, which is a separate
concern and a separate place to change.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GuardianMessage(BaseModel):
    """One inbound message, normalised into Guardian's own vocabulary."""

    # Frozen: a message flows through the pipeline as evidence and should not
    # be mutated in place. extra="forbid": the shape is a contract, and a typo
    # in a mapping should fail loudly rather than being silently dropped.
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str = Field(
        description="Identifier the source assigned to this message.",
        examples=["wamid.HBgLMTY1MDUwNTEyMzQVAgARGBI5QTNDQTVCM0Q0Q0Q2RTY3Q0IA"],
    )
    sender_id: str = Field(
        description="Who sent it, in the source's own identifier space.",
        examples=["16505551234"],
    )
    text: str = Field(
        description="Message body as received. The processor trims surrounding whitespace.",
        examples=["Your account is locked, verify at http://bit.ly/x"],
    )
    received_at: datetime = Field(
        description="When the message was received.",
        examples=["2023-11-14T22:13:20Z"],
    )
    source: str = Field(
        description="Channel the message arrived on, e.g. 'whatsapp'.",
        examples=["whatsapp"],
    )
