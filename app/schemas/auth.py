"""Authentication-related API schemas."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class AuthRegisterRequest(BaseModel):
    """Request payload for creating a new user and initial API key."""

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=255)
    api_key_name: str = Field(default="default", min_length=1, max_length=255)


class AuthSignupRequest(BaseModel):
    """Request payload for browser-friendly email/password account creation."""

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=255)


class AuthLoginRequest(BaseModel):
    """Request payload for browser-friendly email/password login."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=255)


class UserResponse(BaseModel):
    """Public user identity returned by auth endpoints."""

    user_id: UUID
    email: EmailStr
    display_name: str


class AuthRegisterResponse(BaseModel):
    """Response payload for initial user registration."""

    user: UserResponse
    api_key: str
    api_key_prefix: str


class AuthMeResponse(BaseModel):
    """Response payload for the currently authenticated user."""

    user: UserResponse


class AuthSessionResponse(BaseModel):
    """Response payload for password-based sign up or login."""

    user: UserResponse
    access_token: str
    token_type: str = "bearer"


class AuthLogoutResponse(BaseModel):
    """Response payload for logging out one browser session."""

    message: str
