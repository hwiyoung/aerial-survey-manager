"""Short-lived capability tokens for project artifacts and map tiles."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import jwt
from jwt import PyJWTError

from app.config import get_settings

settings = get_settings()

ASSET_TOKEN_TTL_SECONDS = 3600


def create_asset_token(
    *,
    project_id: str | UUID,
    object_name: str,
    purpose: str,
    ttl_seconds: int = ASSET_TOKEN_TTL_SECONDS,
) -> str:
    """Create a signed capability for one project artifact."""
    now = datetime.utcnow()
    payload = {
        "type": "asset",
        "purpose": purpose,
        "project_id": str(project_id),
        "object_name": str(object_name),
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_asset_token(token: str, *, purpose: str) -> dict:
    """Decode an asset token and require the expected purpose."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except PyJWTError as exc:
        raise ValueError("Invalid or expired asset token") from exc

    if payload.get("type") != "asset" or payload.get("purpose") != purpose:
        raise ValueError("Invalid asset token scope")
    if not payload.get("project_id") or not payload.get("object_name"):
        raise ValueError("Invalid asset token payload")
    return payload


def build_project_asset_url(
    project_id: str | UUID,
    object_name: str | None,
) -> str | None:
    """Build a browser-safe URL for a project artifact."""
    if not object_name:
        return None
    token = create_asset_token(
        project_id=project_id,
        object_name=object_name,
        purpose="preview",
    )
    return f"/api/v1/storage/assets/{token}"
