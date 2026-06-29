from __future__ import annotations

from app.api.routes import health as health_routes


def test_livez_returns_ok(anon_client):
    response = anon_client.get("/livez")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_name"] == "pdfReader"


def test_readyz_returns_ok_when_dependencies_are_ready(anon_client, monkeypatch):
    monkeypatch.setattr(health_routes, "_check_database", lambda: "ok")
    monkeypatch.setattr(health_routes, "_check_redis", lambda: "ok")

    response = anon_client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"] == {"database": "ok", "redis": "ok"}


def test_readyz_returns_503_when_any_dependency_is_unavailable(anon_client, monkeypatch):
    monkeypatch.setattr(health_routes, "_check_database", lambda: "ok")
    monkeypatch.setattr(health_routes, "_check_redis", lambda: "error")

    response = anon_client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"] == {"database": "ok", "redis": "error"}
