from __future__ import annotations

from app.db.models import ApiKey, AuthSession, User


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


def test_signup_route_creates_password_user_and_session(anon_client, db_session):
    response = anon_client.post(
        "/auth/signup",
        json={
            "email": "browser@example.com",
            "display_name": "Browser User",
            "password": "supersecret123",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["email"] == "browser@example.com"
    assert payload["access_token"].startswith("pds_")
    assert payload["token_type"] == "bearer"

    stored_user = db_session.query(User).filter(User.email == "browser@example.com").first()
    assert stored_user is not None
    assert stored_user.password_hash is not None

    auth_session = db_session.query(AuthSession).join(User).filter(User.email == "browser@example.com").first()
    assert auth_session is not None
    assert auth_session.token_prefix == payload["access_token"][:12]


def test_login_route_returns_new_auth_session_for_valid_password(anon_client):
    signup_response = anon_client.post(
        "/auth/signup",
        json={
            "email": "login@example.com",
            "display_name": "Login User",
            "password": "supersecret123",
        },
    )
    assert signup_response.status_code == 200

    login_response = anon_client.post(
        "/auth/login",
        json={
            "email": "login@example.com",
            "password": "supersecret123",
        },
    )

    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["user"]["email"] == "login@example.com"
    assert payload["access_token"].startswith("pds_")


def test_auth_me_accepts_password_session_token(anon_client):
    signup_response = anon_client.post(
        "/auth/signup",
        json={
            "email": "session@example.com",
            "display_name": "Session User",
            "password": "supersecret123",
        },
    )
    access_token = signup_response.json()["access_token"]

    response = anon_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "session@example.com"


def test_logout_route_revokes_password_session_token(anon_client):
    signup_response = anon_client.post(
        "/auth/signup",
        json={
            "email": "logout@example.com",
            "display_name": "Logout User",
            "password": "supersecret123",
        },
    )
    access_token = signup_response.json()["access_token"]

    logout_response = anon_client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert logout_response.status_code == 200

    me_response = anon_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_response.status_code == 401
