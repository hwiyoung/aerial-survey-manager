"""Secure download token storage with optional Redis fallback.

This module keeps download preparation artifacts behind short-lived opaque tokens.
It prefers Redis (shared across workers/instances) and falls back to an
in-process in-memory store when Redis is unavailable.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, Mapping

from app.config import get_settings

settings = get_settings()

TOKEN_TTL_SECONDS = 300
_TOKEN_PREFIX = "download-token:"

try:
    import redis.asyncio as redis_async
except Exception:  # pragma: no cover - fallback when redis lib unavailable
    redis_async = None


def _to_serializable(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return [_to_serializable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_serializable(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        return str(value)
    return value


class _MemoryDownloadTokenStore:
    def __init__(self):
        self._tokens: dict[str, tuple[dict[str, Any], float]] = {}

    async def save(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds
        self._tokens[key] = (value, expires_at)

    async def get(self, key: str) -> dict[str, Any] | None:
        payload = self._tokens.get(key)
        if not payload:
            return None

        value, expires_at = payload
        if expires_at <= time.time():
            self._tokens.pop(key, None)
            return None

        return value

    async def delete(self, key: str) -> None:
        self._tokens.pop(key, None)


class _RedisDownloadTokenStore:
    def __init__(self):
        self._client = None

    async def _connect(self):
        if self._client is not None:
            return self._client

        if redis_async is None:
            raise RuntimeError("Redis client not available")

        self._client = redis_async.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        return self._client

    async def save(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        client = await self._connect()
        redis_key = _TOKEN_PREFIX + key
        await client.set(redis_key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)

    async def get(self, key: str) -> dict[str, Any] | None:
        client = await self._connect()
        redis_key = _TOKEN_PREFIX + key
        raw = await client.get(redis_key)
        if not raw:
            return None
        return json.loads(raw)

    async def delete(self, key: str) -> None:
        client = await self._connect()
        redis_key = _TOKEN_PREFIX + key
        await client.delete(redis_key)


_memory_store = _MemoryDownloadTokenStore()
_redis_store = _RedisDownloadTokenStore()


async def _save_token(payload: dict[str, Any], ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)

    now = time.time()
    token_payload = {
        "created_at": now,
        "expires_at": now + ttl_seconds,
        **_to_serializable(payload),
    }

    store_used_redis = True
    try:
        await _redis_store.save(token, token_payload, ttl_seconds)
    except Exception:
        store_used_redis = False
        await _memory_store.save(token, token_payload, ttl_seconds)

    return token


async def _get_token_payload(token: str) -> dict[str, Any] | None:
    if not token:
        return None

    payload: dict[str, Any] | None = None
    try:
        payload = await _redis_store.get(token)
        if payload is not None:
            return payload
    except Exception:
        pass

    payload = await _memory_store.get(token)
    if payload is None:
        return None

    return payload


async def _delete_download_token(token: str) -> None:
    """Delete token payload from all available stores."""
    await _memory_store.delete(token)
    try:
        await _redis_store.delete(token)
    except Exception:
        pass


async def create_download_token(
    *,
    file_path: str,
    filename: str,
    media_type: str,
    file_size: int,
    organization_id: str | None = None,
    project_ids: list[str] | None = None,
    user_id: str | None = None,
    ttl_seconds: int = TOKEN_TTL_SECONDS,
) -> str:
    """Create an opaque one-time token for prepared download access."""
    return await _save_token(
        {
            "file_path": file_path,
            "filename": filename,
            "media_type": media_type,
            "file_size": file_size,
            "organization_id": organization_id,
            "project_ids": project_ids or [],
            "user_id": user_id,
            "one_time": True,
        },
        ttl_seconds=ttl_seconds,
    )


async def consume_download_token(token: str) -> dict[str, Any] | None:
    """Consume and delete the download token if valid."""
    payload = await _get_token_payload(token)
    if not payload:
        return None

    expires_at = float(payload.get("expires_at", 0) or 0)
    if expires_at <= time.time():
        await _delete_download_token(token)
        return None

    await _delete_download_token(token)
    return payload


async def peek_download_token(token: str) -> dict[str, Any] | None:
    """Read token payload without consuming it."""
    payload = await _get_token_payload(token)
    if not payload:
        return None

    expires_at = float(payload.get("expires_at", 0) or 0)
    if expires_at <= time.time():
        await _delete_download_token(token)
        return None

    return payload

async def delete_download_token(token: str) -> None:
    """Delete token payload."""
    await _delete_download_token(token)
