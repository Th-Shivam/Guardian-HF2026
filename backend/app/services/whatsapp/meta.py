"""Meta WhatsApp Cloud API adapter.

Models the Cloud API webhook envelope and normalises it into Guardian's
provider-agnostic ``InboundMessage``. No network calls are made here yet —
``send_text`` is the seam where the Graph API client will land.

Envelope shape (trimmed to what Guardian reads):

    {
      "object": "whatsapp_business_account",
      "entry": [{
        "id": "...",
        "changes": [{
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "16505551234", "profile": {"name": "Asha"}}],
            "messages": [{
              "id": "wamid....", "from": "16505551234",
              "timestamp": "1700000000", "type": "text",
              "text": {"body": "You have won a prize"}
            }]
          }
        }]
      }]
    }
"""

from collections.abc import Mapping
from datetime import datetime, timezone
from secrets import compare_digest
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.logging import get_logger
from app.schemas.whatsapp import InboundMessage, ParsedWebhook, VerificationRequest
from app.services.whatsapp.base import WhatsAppProvider
from app.services.whatsapp.errors import ConfigurationError, PayloadError, VerificationError

logger = get_logger(__name__)

EXPECTED_OBJECT = "whatsapp_business_account"
MESSAGES_FIELD = "messages"
SUBSCRIBE_MODE = "subscribe"
TEXT_TYPE = "text"


class _Base(BaseModel):
    # Meta adds fields over time; ignoring unknowns keeps old deploys working.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _Profile(_Base):
    name: str | None = None


class _Contact(_Base):
    wa_id: str
    profile: _Profile = Field(default_factory=_Profile)


class _Text(_Base):
    body: str


class _Message(_Base):
    id: str
    sender: str = Field(alias="from")
    timestamp: datetime
    type: str
    text: _Text | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _unix_seconds_to_datetime(cls, value: Any) -> Any:
        """Meta sends Unix seconds as a string, e.g. ``"1700000000"``.

        Parsed explicitly rather than leaning on Pydantic's coercion, so a
        garbage value fails here with a clear error instead of being guessed at.
        """
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().lstrip("-").isdigit()):
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        raise ValueError("timestamp must be Unix seconds")


class _Value(_Base):
    messaging_product: str | None = None
    contacts: list[_Contact] = Field(default_factory=list)
    messages: list[_Message] = Field(default_factory=list)
    statuses: list[dict[str, Any]] = Field(default_factory=list)


class _Change(_Base):
    field: str
    value: _Value


class _Entry(_Base):
    id: str | None = None
    changes: list[_Change] = Field(default_factory=list)


class MetaWebhookEnvelope(_Base):
    """Top-level Cloud API webhook body."""

    object: str
    entry: list[_Entry]


class MetaCloudProvider(WhatsAppProvider):
    """Adapter for Meta's WhatsApp Cloud API."""

    name: ClassVar[str] = "meta"

    def __init__(self, *, verify_token: str = "") -> None:
        self._verify_token = verify_token

    def verify_subscription(self, request: VerificationRequest) -> str:
        if not self._verify_token:
            raise ConfigurationError(
                "GUARDIAN_WHATSAPP_VERIFY_TOKEN is not set; refusing to verify the subscription."
            )
        if request.mode != SUBSCRIBE_MODE:
            raise VerificationError(f"Unsupported hub.mode {request.mode!r}.")
        # Constant-time: the token is a shared secret, so leaking its length
        # or prefix through response timing is worth avoiding.
        if not compare_digest(request.token, self._verify_token):
            raise VerificationError("Verification token mismatch.")
        return request.challenge

    def parse_inbound(self, payload: Mapping[str, Any]) -> ParsedWebhook:
        try:
            envelope = MetaWebhookEnvelope.model_validate(payload)
        except ValidationError as exc:
            # Log the detail, return a generic message: the response goes back
            # over the public internet.
            logger.warning("Rejected malformed WhatsApp payload: %s", exc.errors())
            raise PayloadError("Payload does not match the WhatsApp Cloud API webhook schema.") from exc

        if envelope.object != EXPECTED_OBJECT:
            raise PayloadError(
                f"Unsupported webhook object {envelope.object!r}; expected {EXPECTED_OBJECT!r}."
            )

        messages: list[InboundMessage] = []
        ignored = 0

        for entry in envelope.entry:
            for change in entry.changes:
                if change.field != MESSAGES_FIELD:
                    ignored += 1
                    continue

                value = change.value
                # Delivery receipts (sent/delivered/read) arrive on this same
                # webhook and are not user messages.
                ignored += len(value.statuses)
                names = {c.wa_id: c.profile.name for c in value.contacts}

                for raw in value.messages:
                    if raw.type != TEXT_TYPE or raw.text is None:
                        # Media forwarding needs a download step Guardian does
                        # not have yet.
                        logger.info("Ignoring non-text message of type %r", raw.type)
                        ignored += 1
                        continue

                    messages.append(
                        InboundMessage(
                            message_id=raw.id,
                            sender=raw.sender,
                            sender_name=names.get(raw.sender),
                            text=raw.text.body,
                            timestamp=raw.timestamp,
                        )
                    )

        return ParsedWebhook(messages=messages, ignored=ignored)

    async def send_text(self, to: str, body: str) -> str:
        raise NotImplementedError(
            "Outbound delivery is not wired up yet; this is where the Graph API call goes."
        )
