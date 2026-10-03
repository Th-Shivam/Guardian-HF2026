"""Tests for the WhatsApp -> Guardian hand-off.

Covers the adapter (``to_guardian_message``) and the end-to-end webhook path:
provider payload -> internal message -> processor -> acknowledgement.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from app.schemas.whatsapp import InboundMessage
from app.services.processing import GuardianMessage
from app.services.whatsapp.mapping import SOURCE_WHATSAPP, to_guardian_message

ENDPOINT = "/api/whatsapp/webhook"

PayloadFactory = Callable[..., dict[str, Any]]
MessageFactory = Callable[..., dict[str, Any]]


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def test_inbound_message_is_mapped_to_the_internal_model() -> None:
    inbound = InboundMessage(
        message_id="wamid.XYZ",
        sender="447700900123",
        sender_name="Asha",
        text="Click here to claim",
        timestamp=datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
    )

    mapped = to_guardian_message(inbound)

    assert isinstance(mapped, GuardianMessage)
    assert mapped.message_id == "wamid.XYZ"
    assert mapped.sender_id == "447700900123"
    assert mapped.text == "Click here to claim"
    assert mapped.received_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert mapped.source == SOURCE_WHATSAPP


def test_mapping_uses_whatsapp_not_the_vendor_name() -> None:
    """``source`` records the channel the person used, not the Cloud API vendor."""
    inbound = InboundMessage(
        message_id="wamid.XYZ",
        sender="447700900123",
        text="hi",
        timestamp=datetime(2023, 11, 14, tzinfo=timezone.utc),
    )

    assert to_guardian_message(inbound).source == "whatsapp"


def test_mapper_ignores_whatsapp_only_fields() -> None:
    """``sender_name`` has no home in the internal model and must not leak in."""
    inbound = InboundMessage(
        message_id="wamid.XYZ",
        sender="447700900123",
        sender_name="Asha",
        text="hi",
        timestamp=datetime(2023, 11, 14, tzinfo=timezone.utc),
    )

    assert "sender_name" not in to_guardian_message(inbound).model_dump()


# --------------------------------------------------------------------------
# Webhook end to end
# --------------------------------------------------------------------------


def test_valid_message_flows_through_the_pipeline(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(
        messages=[text_message(message_id="wamid.ABC", sender="16505551234")],
        contacts=[{"wa_id": "16505551234", "profile": {"name": "Asha"}}],
    )

    response = client.post(ENDPOINT, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["ignored"] == 0
    assert body["messages"][0]["message_id"] == "wamid.ABC"


def test_processed_message_is_logged(
    client: TestClient,
    meta_payload: PayloadFactory,
    text_message: MessageFactory,
    caplog: Any,
) -> None:
    payload = meta_payload(messages=[text_message(message_id="wamid.LOG", sender="16505551234")])

    with caplog.at_level("INFO"):
        client.post(ENDPOINT, json=payload)

    assert "Guardian received message wamid.LOG from 16505551234" in caplog.text


def test_message_body_is_never_logged_or_echoed(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory, caplog: Any
) -> None:
    secret = "verify at http://phishing.example/steal"
    payload = meta_payload(messages=[text_message(body=secret)])

    with caplog.at_level("INFO"):
        response = client.post(ENDPOINT, json=payload)

    assert secret not in response.text
    assert secret not in caplog.text


# --------------------------------------------------------------------------
# A message the pipeline cannot use is skipped, not fatal.
# Providers disable webhooks that keep returning errors.
# --------------------------------------------------------------------------


def test_empty_message_is_ignored_not_rejected(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(messages=[text_message(body="   ")])

    response = client.post(ENDPOINT, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 0
    assert body["ignored"] == 1
    assert body["messages"] == []


def test_one_empty_message_does_not_drop_its_siblings(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(
        messages=[
            text_message(message_id="wamid.GOOD", body="claim your prize"),
            text_message(message_id="wamid.EMPTY", body=""),
        ]
    )

    body = client.post(ENDPOINT, json=payload).json()

    assert body["accepted"] == 1
    assert body["ignored"] == 1
    assert [m["message_id"] for m in body["messages"]] == ["wamid.GOOD"]


def test_ignored_count_adds_up_across_sources(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    """Provider-level ignores (statuses) and pipeline-level ones are summed."""
    payload = meta_payload(
        messages=[text_message(body="")],
        statuses=[{"id": "wamid.X", "status": "delivered"}],
    )

    body = client.post(ENDPOINT, json=payload).json()

    assert body["accepted"] == 0
    assert body["ignored"] == 2
