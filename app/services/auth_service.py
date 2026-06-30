"""Authentication and API-key management services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import hmac

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ApiKey, AuthSession, User
from app.schemas.auth import AuthMeResponse, AuthRegisterResponse, AuthSessionResponse, UserResponse


def register_user(db: Session, email: str, display_name: str, api_key_name: str) -> AuthRegisterResponse:
    """Create a user and return a freshly issued API key."""

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists.")

    raw_api_key = _generate_api_key()
    api_key_hash = _hash_api_key(raw_api_key)
    key_prefix = raw_api_key[:12]

    user = User(email=email, display_name=display_name)
    db.add(user)
    db.flush()

    api_key = ApiKey(
        user_id=user.id,
        name=api_key_name,
        key_prefix=key_prefix,
        key_hash=api_key_hash,
    )
    db.add(api_key)
    db.commit()
    db.refresh(user)

    return AuthRegisterResponse(
        user=_build_user_response(user),
        api_key=raw_api_key,
        api_key_prefix=key_prefix,
    )


def signup_user_with_password(db: Session, email: str, display_name: str, password: str) -> AuthSessionResponse:
    """Create a user with password auth and issue a browser session token."""

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists.")

    user = User(
        email=email,
        display_name=display_name,
        password_hash=_hash_password(password),
    )
    db.add(user)
    db.flush()

    raw_session_token, auth_session = _build_auth_session(user.id)
    db.add(auth_session)
    db.commit()
    db.refresh(user)

    return AuthSessionResponse(
        user=_build_user_response(user),
        access_token=raw_session_token,
    )


def login_user_with_password(db: Session, email: str, password: str) -> AuthSessionResponse:
    """Authenticate a user with email/password and issue a new browser session token."""

    user = db.query(User).filter(User.email == email).first()
    if user is None or user.password_hash is None or not _verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    raw_session_token, auth_session = _build_auth_session(user.id)
    db.add(auth_session)
    db.commit()
    db.refresh(user)

    return AuthSessionResponse(
        user=_build_user_response(user),
        access_token=raw_session_token,
    )


def authenticate_api_key(db: Session, raw_api_key: str) -> User:
    """Resolve one bearer API key to its owning active user."""

    api_key_hash = _hash_api_key(raw_api_key)
    api_key = (
        db.query(ApiKey)
        .join(User)
        .filter(ApiKey.key_hash == api_key_hash, ApiKey.revoked_at.is_(None))
        .first()
    )
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")

    api_key.last_used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(api_key)
    return api_key.user


def authenticate_bearer_credential(db: Session, raw_bearer_token: str) -> User:
    """Authenticate either a browser auth session or a legacy API key."""

    auth_session = _find_auth_session(db, raw_bearer_token)
    if auth_session is not None:
        auth_session.last_used_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(auth_session)
        return auth_session.user

    return authenticate_api_key(db, raw_bearer_token)


def revoke_auth_session(db: Session, raw_bearer_token: str) -> None:
    """Revoke one browser auth session token."""

    auth_session = _find_auth_session(db, raw_bearer_token)
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token.")

    auth_session.revoked_at = datetime.now(timezone.utc)
    db.commit()


def build_auth_me_response(user: User) -> AuthMeResponse:
    """Build the current-user payload for one authenticated user."""

    return AuthMeResponse(user=_build_user_response(user))


def _build_user_response(user: User) -> UserResponse:
    """Convert one user model into the shared public response shape."""

    return UserResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
    )


def _generate_api_key() -> str:
    """Return a new plaintext API key."""

    return f"pdr_{secrets.token_urlsafe(32)}"


def _generate_auth_session_token() -> str:
    """Return a new plaintext browser auth token."""

    return f"pds_{secrets.token_urlsafe(32)}"


def _hash_api_key(raw_api_key: str) -> str:
    """Return the stable SHA-256 hash for one plaintext API key."""

    return hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()


def _build_auth_session(user_id) -> tuple[str, AuthSession]:
    """Create one persisted auth-session model plus its plaintext token."""

    settings = get_settings()
    raw_token = _generate_auth_session_token()
    now = datetime.now(timezone.utc)
    auth_session = AuthSession(
        user_id=user_id,
        token_prefix=raw_token[:12],
        token_hash=_hash_api_key(raw_token),
        expires_at=now + timedelta(days=settings.auth_session_ttl_days),
        last_used_at=now,
    )
    return raw_token, auth_session


def _find_auth_session(db: Session, raw_bearer_token: str) -> AuthSession | None:
    """Resolve a raw bearer token to one active browser auth session."""

    now = datetime.now(timezone.utc)
    return (
        db.query(AuthSession)
        .join(User)
        .filter(
            AuthSession.token_hash == _hash_api_key(raw_bearer_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .first()
    )


def _hash_password(password: str) -> str:
    """Return a PBKDF2-based password hash string."""

    iterations = 600_000
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify one plaintext password against the stored PBKDF2 hash string."""

    algorithm, iterations, salt, expected_digest = stored_hash.split("$", 3)
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return hmac.compare_digest(digest, expected_digest)
