"""Shared pytest fixtures.

``pytest.ini`` puts ``backend/`` on the import path, so the application is
imported as ``app.*`` exactly as it is at runtime.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.services.whatsapp import MetaCloudProvider

VERIFY_TOKEN = "test-verify-token"


def _build_app(settings: Settings) -> TestClient:
    """Build a TestClient whose dependencies really use ``settings``.

    ``create_app`` stores settings on ``app.state``, but routes resolve them
    through ``Depends(get_settings)`` — which returns the lru_cached,
    process-wide instance. Without this override the app under test would
    silently read the real environment.
    """
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture(scope="session")
def verify_token() -> str:
    """The webhook verify token the test app is configured with."""
    return VERIFY_TOKEN


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Deterministic settings, independent of any local .env file."""
    return Settings(
        env="test",
        debug=False,
        cors_origins="http://testserver",
        whatsapp_provider="meta",
        whatsapp_verify_token=VERIFY_TOKEN,
    )


@pytest.fixture(scope="session")
def client(settings: Settings) -> Iterator[TestClient]:
    """Test client bound to a freshly built app (runs lifespan hooks)."""
    with _build_app(settings) as test_client:
        yield test_client


@pytest.fixture
def client_factory() -> Iterator[Callable[[Settings], TestClient]]:
    """Build extra clients with bespoke settings; all are closed on teardown."""
    opened: list[TestClient] = []

    def _factory(settings: Settings) -> TestClient:
        test_client = _build_app(settings)
        test_client.__enter__()
        opened.append(test_client)
        return test_client

    yield _factory

    for test_client in reversed(opened):
        test_client.__exit__(None, None, None)


@pytest.fixture
def provider() -> MetaCloudProvider:
    """A Meta adapter configured with the test verify token."""
    return MetaCloudProvider(verify_token=VERIFY_TOKEN)


@pytest.fixture
def text_message() -> Callable[..., dict[str, Any]]:
    """Factory for one Cloud API message object."""

    def _build(
        *,
        message_id: str = "wamid.TEST0001",
        sender: str = "16505551234",
        body: str = "Your account is locked, verify at http://bit.ly/x",
        timestamp: str = "1700000000",
        message_type: str = "text",
        include_text: bool = True,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "id": message_id,
            "from": sender,
            "timestamp": timestamp,
            "type": message_type,
        }
        if include_text:
            message["text"] = {"body": body}
        return message

    return _build


@pytest.fixture
def meta_payload() -> Callable[..., dict[str, Any]]:
    """Factory for a full Cloud API webhook envelope."""

    def _build(
        *,
        messages: list[dict[str, Any]] | None = None,
        statuses: list[dict[str, Any]] | None = None,
        contacts: list[dict[str, Any]] | None = None,
        field: str = "messages",
        obj: str = "whatsapp_business_account",
        entries: int = 1,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {"messaging_product": "whatsapp"}
        if contacts is not None:
            value["contacts"] = contacts
        if messages is not None:
            value["messages"] = messages
        if statuses is not None:
            value["statuses"] = statuses

        return {
            "object": obj,
            "entry": [
                {"id": "102290129340398", "changes": [{"field": field, "value": value}]}
                for _ in range(entries)
            ],
        }

    return _build
