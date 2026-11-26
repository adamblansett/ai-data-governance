import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import jwt
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core.config import Settings
from app.db.session import get_app_settings

Role = Literal["viewer", "analyst", "steward", "admin"]

ROLE_LEVELS: dict[Role, int] = {
    "viewer": 1,
    "analyst": 2,
    "steward": 3,
    "admin": 4,
}

ROLE_PERMISSIONS: dict[Role, list[str]] = {
    "viewer": [
        "read:proposals",
        "read:audit",
        "read:vault_stats",
        "read:connectors",
        "read:reports",
    ],
    "analyst": [
        "read:proposals",
        "read:audit",
        "read:vault_stats",
        "read:connectors",
        "read:reports",
        "write:scans",
        "write:proposals",
        "write:jobs",
    ],
    "steward": [
        "read:proposals",
        "read:audit",
        "read:vault_stats",
        "read:connectors",
        "read:reports",
        "write:scans",
        "write:proposals",
        "write:jobs",
        "execute:detokenize",
        "execute:approvals",
    ],
    "admin": [
        "read:proposals",
        "read:audit",
        "read:vault_stats",
        "read:connectors",
        "read:reports",
        "write:scans",
        "write:proposals",
        "write:jobs",
        "execute:detokenize",
        "execute:approvals",
        "admin:connectors",
    ],
}


class Principal(BaseModel):
    """Authenticated (or dev-fallback) request identity and role."""

    sub: str
    role: Role
    auth_method: Literal["jwt", "api_key", "dev_fallback"]


def create_access_token(
    settings: Settings,
    *,
    sub: str,
    role: Role,
) -> tuple[str, datetime]:
    """Create a signed HS256 JWT access token."""
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=max(1, settings.auth_token_ttl_minutes))
    payload = {
        "sub": sub,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.auth_secret_key, algorithm="HS256")
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> Principal:
    """Validate and decode an HS256 JWT access token into a Principal."""
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid or expired JWT access token.") from exc

    sub = str(payload.get("sub", "")).strip()
    raw_role = str(payload.get("role", "")).strip().lower()
    if not sub or raw_role not in ROLE_LEVELS:
        raise ValueError("JWT claims missing valid 'sub' or 'role'.")
    return Principal(sub=sub, role=cast(Role, raw_role), auth_method="jwt")


def resolve_api_key(settings: Settings, api_key: str) -> Principal | None:
    """Match an incoming API key against configured key:role:subject entries."""
    candidate = api_key.strip()
    if not candidate or not settings.auth_api_keys.strip():
        return None

    matched: Principal | None = None
    for raw_entry in settings.auth_api_keys.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split(":")]
        if len(parts) < 2:
            continue
        configured_key = parts[0]
        raw_role = parts[1].lower()
        subject = parts[2] if len(parts) >= 3 and parts[2] else f"apikey-{raw_role}"
        if (
            raw_role in ROLE_LEVELS
            and hmac.compare_digest(candidate.encode("utf-8"), configured_key.encode("utf-8"))
        ):
            matched = Principal(sub=subject, role=cast(Role, raw_role), auth_method="api_key")
    return matched


def resolve_actor(principal: Principal, requested_actor: str) -> str:
    """Enforce authenticated subject identity while allowing dev-fallback actor names."""
    if principal.auth_method != "dev_fallback":
        return principal.sub
    return requested_actor.strip() or principal.sub


def require_role(min_role: Role) -> Callable[..., Principal]:
    """Build a FastAPI dependency enforcing minimum RBAC role."""

    def _dependency(
        request: Request,
        settings: Settings = Depends(get_app_settings),
    ) -> Principal:
        auth_header = request.headers.get("Authorization", "").strip()
        api_key = request.headers.get("X-API-Key", "").strip()

        principal: Principal | None = None
        if auth_header:
            scheme, _, token = auth_header.partition(" ")
            if scheme.lower() != "bearer" or not token.strip():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Authorization header; expected Bearer token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            try:
                principal = decode_access_token(settings, token.strip())
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=str(exc),
                    headers={"WWW-Authenticate": "Bearer"},
                ) from exc
        elif api_key:
            principal = resolve_api_key(settings, api_key)
            if principal is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key.",
                )
        else:
            if settings.auth_required:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            principal = Principal(sub="dev-steward", role="admin", auth_method="dev_fallback")

        if ROLE_LEVELS[principal.role] < ROLE_LEVELS[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: role '{min_role}' or higher required.",
            )
        return principal

    return _dependency
