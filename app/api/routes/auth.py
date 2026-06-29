"""Authentication routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import AuthMeResponse, AuthRegisterRequest, AuthRegisterResponse
from app.services.auth_service import build_auth_me_response, register_user

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


@router.get("/auth/me", response_model=AuthMeResponse)
def get_me_route(current_user: Annotated[User, Depends(get_current_user)]) -> AuthMeResponse:
    """Return the currently authenticated user."""

    return build_auth_me_response(current_user)
