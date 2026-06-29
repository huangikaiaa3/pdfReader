"""Authentication and API-key management services."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import secrets

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import ApiKey, User
from app.schemas.auth import AuthMeResponse, AuthRegisterResponse, UserResponse


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


def _hash_api_key(raw_api_key: str) -> str:
    """Return the stable SHA-256 hash for one plaintext API key."""

    return hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()
