"""Shared slowapi Limiter instance — avoids circular imports between main and routes.

Uses Redis as shared backend so rate limits work correctly across multiple ECS tasks.
Falls back to in-memory if REDIS_URL is unreachable (e.g., local dev).
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

_redis_url = os.environ.get("REDIS_URL", "")

_storage_uri = _redis_url if _redis_url.startswith(("redis://", "rediss://")) else "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri,
    strategy="fixed-window",
)
