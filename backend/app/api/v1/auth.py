from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.security import (
    ROLE_PERMISSIONS,
    Principal,
    Role,
    create_access_token,
    require_role,
    resolve_api_key,
)
from app.db.session import get_app_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    """Request to mint a scoped JWT access token."""

    username: str = Field(default="data-steward", min_length=1, max_length=120)
    role: Role = "steward"
    api_key: str | None = None


class TokenResponse(BaseModel):
    """Issued bearer JWT metadata."""

    access_token: str
    token_type: str = "bearer"
    sub: str
    role: Role
    expires_at: datetime


class WhoAmIResponse(BaseModel):
    """Active principal identity and effective RBAC permissions."""

    sub: str
    role: Role
    auth_method: str
    auth_required: bool
    permissions: list[str]


@router.post("/token", response_model=TokenResponse)
async def issue_token(
    body: TokenRequest,
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse:
    """Issue an HS256 JWT token (requires configured API key in production)."""
    is_prod = settings.app_env.strip().lower() == "production"
    target_sub = body.username.strip()
    target_role: Role = body.role

    if body.api_key:
        key_principal = resolve_api_key(settings, body.api_key)
        if key_principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key.",
            )
        target_sub = key_principal.sub
        target_role = key_principal.role
    elif is_prod:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key required to mint JWT tokens in production.",
        )

    token, expires_at = create_access_token(settings, sub=target_sub, role=target_role)
    return TokenResponse(
        access_token=token,
        sub=target_sub,
        role=target_role,
        expires_at=expires_at,
    )


@router.get("/me", response_model=WhoAmIResponse)
async def auth_me(
    principal: Principal = Depends(require_role("viewer")),
    settings: Settings = Depends(get_app_settings),
) -> WhoAmIResponse:
    """Return active principal identity and granted permission scopes."""
    return WhoAmIResponse(
        sub=principal.sub,
        role=principal.role,
        auth_method=principal.auth_method,
        auth_required=settings.auth_required,
        permissions=ROLE_PERMISSIONS[principal.role],
    )
