"""WhatsApp webhook endpoints.

Thin by design: both handlers delegate to the configured
:class:`~app.services.whatsapp.base.WhatsAppProvider` and translate nothing
themselves. The body is accepted as a raw mapping rather than a Meta-shaped
model so the route stays provider-agnostic — validation belongs to the
adapter that owns the wire format.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import PlainTextResponse

from app.api.dependencies import get_message_processor
from app.core.logging import get_logger
from app.schemas.whatsapp import AcknowledgedMessage, VerificationRequest, WebhookAck
from app.services.processing import InvalidMessageError, MessageProcessor
from app.services.whatsapp import WhatsAppProvider, get_whatsapp_provider
from app.services.whatsapp.mapping import to_guardian_message

logger = get_logger(__name__)

router = APIRouter()

ProviderDep = Annotated[WhatsAppProvider, Depends(get_whatsapp_provider)]
ProcessorDep = Annotated[MessageProcessor, Depends(get_message_processor)]

_EXAMPLE_PAYLOAD: dict[str, Any] = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "102290129340398",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "contacts": [{"wa_id": "16505551234", "profile": {"name": "Asha"}}],
                        "messages": [
                            {
                                "id": "wamid.HBgLMTY1MDU1NTEyMzQVAgASGBQz",
                                "from": "16505551234",
                                "timestamp": "1700000000",
                                "type": "text",
                                "text": {"body": "Your account is locked, verify at http://bit.ly/x"},
                            }
                        ],
                    },
                }
            ],
        }
    ],
}


@router.get(
    "/webhook",
    response_class=PlainTextResponse,
    summary="Verify the webhook subscription",
    responses={
        200: {"description": "Challenge echoed back verbatim."},
        403: {"description": "Bad mode or token."},
    },
)
def verify_webhook(
    provider: ProviderDep,
    hub_mode: Annotated[str, Query(alias="hub.mode", examples=["subscribe"])],
    hub_verify_token: Annotated[str, Query(alias="hub.verify_token")],
    hub_challenge: Annotated[str, Query(alias="hub.challenge")],
) -> str:
    """Complete a provider's subscription handshake.

    The challenge must come back as raw text, not JSON — providers compare the
    response body byte for byte.
    """
    challenge = provider.verify_subscription(
        VerificationRequest(mode=hub_mode, token=hub_verify_token, challenge=hub_challenge)
    )
    logger.info("WhatsApp subscription verified for provider %r", provider.name)
    return challenge


@router.post(
    "/webhook",
    response_model=WebhookAck,
    summary="Receive an inbound message payload",
    responses={
        200: {"description": "Payload understood; messages extracted."},
        422: {"description": "Payload did not match the provider's schema."},
    },
)
def receive_webhook(
    provider: ProviderDep,
    processor: ProcessorDep,
    payload: Annotated[dict[str, Any], Body(examples=[_EXAMPLE_PAYLOAD])],
) -> WebhookAck:
    """Accept a webhook delivery, run it through the pipeline, and acknowledge.

    Each extracted message is normalised into Guardian's internal model and
    handed to the message processor. A well-formed delivery that carries
    nothing to analyse — no messages at all, or a message that fails
    processing — is still a success: it returns 200 with a reduced ``accepted``
    count. Providers retry on non-2xx and eventually disable a webhook that
    keeps failing, so only genuinely malformed bodies error.

    Offline signals and configured SerpApi evidence are collected internally.
    The acknowledgement contains neither message content nor search evidence;
    nothing is persisted and no final verdict or outbound reply is produced.
    """
    parsed = provider.parse_inbound(payload)

    accepted: list[AcknowledgedMessage] = []
    ignored = parsed.ignored

    for message in parsed.messages:
        try:
            processed = processor.process_with_analysis(to_guardian_message(message))
        except InvalidMessageError as exc:
            # Deliberate: a message we cannot use is skipped, not fatal. The
            # reason is logged server-side and never reflected to the caller.
            logger.warning("Skipping unprocessable message: %s", exc)
            ignored += 1
            continue

        accepted.append(
            AcknowledgedMessage(
                message_id=processed.message.message_id,
                sender=processed.message.sender_id,
                timestamp=processed.message.received_at,
            )
        )

    logger.info(
        "WhatsApp webhook: provider=%s accepted=%d ignored=%d",
        provider.name,
        len(accepted),
        ignored,
    )

    return WebhookAck(
        provider=provider.name,
        accepted=len(accepted),
        ignored=ignored,
        messages=accepted,
    )
