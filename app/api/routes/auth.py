"""Authentication routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    AuthLoginRequest,
    AuthLogoutResponse,
    AuthMeResponse,
    AuthRegisterRequest,
    AuthRegisterResponse,
    AuthSessionResponse,
    AuthSignupRequest,
)
from app.services.auth_service import build_auth_me_response, login_user_with_password, register_user, revoke_auth_session, signup_user_with_password

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=AuthRegisterResponse)
def register_route(payload: AuthRegisterRequest, db: Session = Depends(get_db)) -> AuthRegisterResponse:
    """Create a new user and initial API key."""

    return register_user(
        db=db,
        email=payload.email,
        display_name=payload.display_name,
        api_key_name=payload.api_key_name,
    )


@router.post("/auth/signup", response_model=AuthSessionResponse)
def signup_route(payload: AuthSignupRequest, db: Session = Depends(get_db)) -> AuthSessionResponse:
    """Create a new password-auth user and issue a browser session token."""

    return signup_user_with_password(
        db=db,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
    )


@router.post("/auth/login", response_model=AuthSessionResponse)
def login_route(payload: AuthLoginRequest, db: Session = Depends(get_db)) -> AuthSessionResponse:
    """Authenticate with email/password and return a browser session token."""

    return login_user_with_password(
        db=db,
        email=payload.email,
        password=payload.password,
    )


@router.get("/auth/me", response_model=AuthMeResponse)
def get_me_route(current_user: Annotated[User, Depends(get_current_user)]) -> AuthMeResponse:
    """Return the currently authenticated user."""

    return build_auth_me_response(current_user)


@router.post("/auth/logout", response_model=AuthLogoutResponse)
def logout_route(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> AuthLogoutResponse:
    """Revoke one browser auth session token."""

    if authorization is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header is required.")

    _, _, token = authorization.partition(" ")
    revoke_auth_session(db=db, raw_bearer_token=token)
    return AuthLogoutResponse(message=f"Signed out {current_user.display_name}.")
