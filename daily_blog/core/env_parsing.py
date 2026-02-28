"""Typed helpers for reading environment variables."""
from __future__ import annotations

import os


def env_bool(name: str, default: bool = False) -> bool:
    """Return True if the env var is set to 1/true/yes/on (case-insensitive)."""
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


def env_int(name: str, default: int = 0) -> int:
    """Return the env var as int, or default if missing/invalid."""
    try:
        return int(os.getenv(name, ""))
    except (ValueError, TypeError):
        return default
