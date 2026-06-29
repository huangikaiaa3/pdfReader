from __future__ import annotations

from app.db.models import ApiKey, User


def test_register_route_creates_user_and_api_key(anon_client, db_session):
    response = anon_client.post(
        "/auth/register",
        json={
            "email": "owner@example.com",
            "display_name": "Owner",
            "api_key_name": "local-dev",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["email"] == "owner@example.com"
    assert payload["user"]["display_name"] == "Owner"
    assert payload["api_key"].startswith("pdr_")
    assert payload["api_key_prefix"] == payload["api_key"][:12]

    assert db_session.query(User).filter(User.email == "owner@example.com").count() == 1
    stored_api_key = db_session.query(ApiKey).join(User).filter(User.email == "owner@example.com").first()
    assert stored_api_key is not None
    assert stored_api_key.key_prefix == payload["api_key_prefix"]


def test_auth_me_returns_current_user(client, current_user):
    response = client.get("/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["user_id"] == str(current_user.id)
    assert payload["user"]["email"] == current_user.email
    assert payload["user"]["display_name"] == current_user.display_name
