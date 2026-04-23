"""
app/core/cache.py — Simple in-memory TTL cache for AI-generated content.

Prevents AI responses from changing on every page refresh.
Cache survives as long as the server process is running.
"""

import time
from typing import Any, Optional

_store: dict = {}  # key → (value, expires_at)


def get(key: str) -> Optional[Any]:
    entry = _store.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        del _store[key]
        return None
    return value


def set(key: str, value: Any, ttl_seconds: int = 4 * 3600) -> None:
    _store[key] = (value, time.time() + ttl_seconds)


def delete(key: str) -> None:
    _store.pop(key, None)


def invalidate_prefix(prefix: str) -> None:
    """Delete all keys that start with the given prefix."""
    keys = [k for k in _store if k.startswith(prefix)]
    for k in keys:
        del _store[k]
