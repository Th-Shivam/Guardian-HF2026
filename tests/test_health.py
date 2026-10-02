"""Smoke tests proving the API boots and serves its meta endpoints."""

from fastapi.testclient import TestClient


def test_root_returns_service_info(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Guardian"
    assert body["docs_url"] == "/docs"
    assert body["version"]


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Guardian"


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/nope").status_code == 404
