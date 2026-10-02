"""Shared pytest fixtures.

``pytest.ini`` puts ``backend/`` on the import path, so the application is
imported as ``app.*`` exactly as it is at runtime.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Deterministic settings, independent of any local .env file."""
    return Settings(env="test", debug=False, cors_origins="http://testserver")


@pytest.fixture(scope="session")
def client(settings: Settings) -> Iterator[TestClient]:
    """Test client bound to a freshly built app (runs lifespan hooks)."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client
