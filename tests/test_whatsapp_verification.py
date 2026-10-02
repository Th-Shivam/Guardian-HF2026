"""Subscription handshake (GET /api/whatsapp/webhook)."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.config import Settings

ENDPOINT = "/api/whatsapp/webhook"


def _params(token: str, *, mode: str = "subscribe", challenge: str = "1158201444") -> dict[str, str]:
    return {"hub.mode": mode, "hub.verify_token": token, "hub.challenge": challenge}


def test_valid_handshake_echoes_challenge(client: TestClient, verify_token: str) -> None:
    response = client.get(ENDPOINT, params=_params(verify_token, challenge="1158201444"))

    assert response.status_code == 200
    # Providers compare the body byte for byte, so it must be bare text.
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


def test_wrong_token_is_rejected(client: TestClient) -> None:
    response = client.get(ENDPOINT, params=_params("not-the-token"))

    assert response.status_code == 403
    assert "mismatch" in response.json()["detail"].lower()


def test_wrong_mode_is_rejected(client: TestClient, verify_token: str) -> None:
    response = client.get(ENDPOINT, params=_params(verify_token, mode="unsubscribe"))

    assert response.status_code == 403


def test_missing_challenge_is_unprocessable(client: TestClient, verify_token: str) -> None:
    params = _params(verify_token)
    del params["hub.challenge"]

    assert client.get(ENDPOINT, params=params).status_code == 422


def test_missing_all_params_is_unprocessable(client: TestClient) -> None:
    assert client.get(ENDPOINT).status_code == 422


def test_unset_verify_token_fails_closed(
    client_factory: Callable[[Settings], TestClient],
) -> None:
    """An unconfigured token must error, never accept an arbitrary one."""
    unconfigured = client_factory(Settings(env="test", whatsapp_verify_token=""))

    response = unconfigured.get(ENDPOINT, params=_params("anything"))

    assert response.status_code == 500
    # The env var name is logged server-side; the client gets a generic message.
    assert "GUARDIAN_WHATSAPP_VERIFY_TOKEN" not in response.text
