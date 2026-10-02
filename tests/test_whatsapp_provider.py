"""Unit tests for the provider layer, without going through HTTP."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pytest

from app.config import Settings
from app.schemas.whatsapp import VerificationRequest
from app.services.whatsapp import (
    ConfigurationError,
    MetaCloudProvider,
    PayloadError,
    VerificationError,
    WhatsAppProvider,
    build_provider,
)

PayloadFactory = Callable[..., dict[str, Any]]
MessageFactory = Callable[..., dict[str, Any]]


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def test_parse_extracts_all_four_fields(
    provider: MetaCloudProvider, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(
        messages=[
            text_message(
                message_id="wamid.XYZ",
                sender="447700900123",
                body="Click here to claim",
                timestamp="1700000000",
            )
        ],
    )

    parsed = provider.parse_inbound(payload)

    (message,) = parsed.messages
    assert message.message_id == "wamid.XYZ"
    assert message.sender == "447700900123"
    assert message.text == "Click here to claim"
    assert message.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert parsed.ignored == 0


def test_timestamp_is_timezone_aware_utc(
    provider: MetaCloudProvider, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    parsed = provider.parse_inbound(meta_payload(messages=[text_message()]))

    assert parsed.messages[0].timestamp.tzinfo is timezone.utc


def test_sender_name_resolved_from_contacts(
    provider: MetaCloudProvider, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(
        messages=[text_message(sender="16505551234")],
        contacts=[{"wa_id": "16505551234", "profile": {"name": "Asha"}}],
    )

    assert provider.parse_inbound(payload).messages[0].sender_name == "Asha"


def test_sender_name_is_none_without_a_matching_contact(
    provider: MetaCloudProvider, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(
        messages=[text_message(sender="16505551234")],
        contacts=[{"wa_id": "99999999999", "profile": {"name": "Someone Else"}}],
    )

    assert provider.parse_inbound(payload).messages[0].sender_name is None


def test_unknown_fields_are_tolerated(
    provider: MetaCloudProvider, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    """Meta adds fields over time; old deploys must not start failing."""
    payload = meta_payload(messages=[text_message()])
    payload["entry"][0]["changes"][0]["value"]["some_future_field"] = {"nested": True}

    assert provider.parse_inbound(payload).messages[0].message_id == "wamid.TEST0001"


def test_malformed_payload_raises_payload_error(provider: MetaCloudProvider) -> None:
    with pytest.raises(PayloadError):
        provider.parse_inbound({"object": "whatsapp_business_account"})


def test_wrong_object_raises_payload_error(
    provider: MetaCloudProvider, meta_payload: PayloadFactory
) -> None:
    with pytest.raises(PayloadError, match="instagram"):
        provider.parse_inbound(meta_payload(obj="instagram"))


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def test_verify_returns_challenge(provider: MetaCloudProvider, verify_token: str) -> None:
    request = VerificationRequest(mode="subscribe", token=verify_token, challenge="42")

    assert provider.verify_subscription(request) == "42"


def test_verify_rejects_bad_token(provider: MetaCloudProvider) -> None:
    request = VerificationRequest(mode="subscribe", token="wrong", challenge="42")

    with pytest.raises(VerificationError):
        provider.verify_subscription(request)


def test_verify_rejects_bad_mode(provider: MetaCloudProvider, verify_token: str) -> None:
    request = VerificationRequest(mode="delete", token=verify_token, challenge="42")

    with pytest.raises(VerificationError):
        provider.verify_subscription(request)


def test_verify_requires_configured_token() -> None:
    unconfigured = MetaCloudProvider(verify_token="")
    request = VerificationRequest(mode="subscribe", token="", challenge="42")

    with pytest.raises(ConfigurationError):
        unconfigured.verify_subscription(request)


# --------------------------------------------------------------------------
# Contract and registry
# --------------------------------------------------------------------------


def test_meta_provider_satisfies_the_abstraction(provider: MetaCloudProvider) -> None:
    assert isinstance(provider, WhatsAppProvider)
    assert MetaCloudProvider.name == "meta"


def test_outbound_send_is_an_unimplemented_seam(provider: MetaCloudProvider) -> None:
    with pytest.raises(NotImplementedError):
        asyncio.run(provider.send_text("16505551234", "hello"))


def test_registry_builds_configured_provider(verify_token: str) -> None:
    built = build_provider(Settings(whatsapp_provider="meta", whatsapp_verify_token=verify_token))

    assert isinstance(built, MetaCloudProvider)
    assert built.verify_subscription(
        VerificationRequest(mode="subscribe", token=verify_token, challenge="ok")
    ) == "ok"


def test_registry_is_case_insensitive(verify_token: str) -> None:
    assert isinstance(
        build_provider(Settings(whatsapp_provider="  META ", whatsapp_verify_token=verify_token)),
        MetaCloudProvider,
    )


def test_registry_rejects_unknown_provider() -> None:
    with pytest.raises(ConfigurationError, match="twilio"):
        build_provider(Settings(whatsapp_provider="twilio"))
