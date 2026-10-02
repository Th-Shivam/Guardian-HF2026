"""Inbound payload handling (POST /api/whatsapp/webhook)."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

ENDPOINT = "/api/whatsapp/webhook"

PayloadFactory = Callable[..., dict[str, Any]]
MessageFactory = Callable[..., dict[str, Any]]


# --------------------------------------------------------------------------
# Valid payloads
# --------------------------------------------------------------------------


def test_text_message_is_accepted_and_extracted(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(
        messages=[text_message(message_id="wamid.ABC", sender="16505551234", timestamp="1700000000")],
        contacts=[{"wa_id": "16505551234", "profile": {"name": "Asha"}}],
    )

    response = client.post(ENDPOINT, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["provider"] == "meta"
    assert body["accepted"] == 1
    assert body["ignored"] == 0

    (acknowledged,) = body["messages"]
    assert acknowledged["message_id"] == "wamid.ABC"
    assert acknowledged["sender"] == "16505551234"
    assert datetime.fromisoformat(acknowledged["timestamp"]) == datetime(
        2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc
    )


def test_ack_does_not_echo_message_body(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    """Guardian handles hostile content; it should not reflect it back."""
    secret = "verify at http://phishing.example/steal"
    payload = meta_payload(messages=[text_message(body=secret)])

    response = client.post(ENDPOINT, json=payload)

    assert response.status_code == 200
    assert secret not in response.text


def test_multiple_messages_across_entries_are_all_accepted(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(
        messages=[text_message(message_id="wamid.1"), text_message(message_id="wamid.2")],
        entries=2,
    )

    body = client.post(ENDPOINT, json=payload).json()

    assert body["accepted"] == 4
    assert [m["message_id"] for m in body["messages"]] == [
        "wamid.1",
        "wamid.2",
        "wamid.1",
        "wamid.2",
    ]


# --------------------------------------------------------------------------
# Valid envelopes carrying nothing to analyse — must still be 200.
# Providers retry on non-2xx and disable webhooks that keep failing.
# --------------------------------------------------------------------------


def test_delivery_statuses_are_ignored_not_rejected(
    client: TestClient, meta_payload: PayloadFactory
) -> None:
    payload = meta_payload(statuses=[{"id": "wamid.X", "status": "delivered"}])

    response = client.post(ENDPOINT, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 0
    assert body["ignored"] == 1


def test_non_text_message_is_ignored(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(
        messages=[text_message(message_type="image", include_text=False)]
    )

    body = client.post(ENDPOINT, json=payload).json()

    assert body["accepted"] == 0
    assert body["ignored"] == 1


def test_other_subscription_field_is_ignored(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(messages=[text_message()], field="account_alerts")

    body = client.post(ENDPOINT, json=payload).json()

    assert body["accepted"] == 0
    assert body["ignored"] == 1


def test_envelope_with_no_entries_is_accepted(client: TestClient) -> None:
    response = client.post(
        ENDPOINT, json={"object": "whatsapp_business_account", "entry": []}
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "received",
        "provider": "meta",
        "accepted": 0,
        "ignored": 0,
        "messages": [],
    }


# --------------------------------------------------------------------------
# Malformed payloads
# --------------------------------------------------------------------------


def test_missing_entry_is_rejected(client: TestClient) -> None:
    response = client.post(ENDPOINT, json={"object": "whatsapp_business_account"})

    assert response.status_code == 422
    assert "schema" in response.json()["detail"].lower()


def test_unknown_object_is_rejected(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(messages=[text_message()], obj="instagram")

    response = client.post(ENDPOINT, json=payload)

    assert response.status_code == 422
    assert "instagram" in response.json()["detail"]


def test_message_missing_id_is_rejected(
    client: TestClient, meta_payload: PayloadFactory
) -> None:
    payload = meta_payload(
        messages=[{"from": "16505551234", "timestamp": "1700000000", "type": "text", "text": {"body": "hi"}}]
    )

    assert client.post(ENDPOINT, json=payload).status_code == 422


def test_non_numeric_timestamp_is_rejected(
    client: TestClient, meta_payload: PayloadFactory, text_message: MessageFactory
) -> None:
    payload = meta_payload(messages=[text_message(timestamp="last-tuesday")])

    assert client.post(ENDPOINT, json=payload).status_code == 422


def test_empty_object_is_rejected(client: TestClient) -> None:
    assert client.post(ENDPOINT, json={}).status_code == 422


def test_array_body_is_rejected(client: TestClient) -> None:
    assert client.post(ENDPOINT, json=[1, 2, 3]).status_code == 422


def test_no_body_is_rejected(client: TestClient) -> None:
    assert client.post(ENDPOINT).status_code == 422
