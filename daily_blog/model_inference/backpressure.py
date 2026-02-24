import logging
import threading
import time
from typing import Callable

DEFAULT_GEMINI_QUOTA_BACKPRESSURE_SECONDS = 300
DEFAULT_GEMINI_MISSING_KEY_BACKPRESSURE_SECONDS = 1800
GEMINI_MISSING_KEY_PATTERNS = ("google_api_key is required",)
GEMINI_QUOTA_PATTERNS = ("resource_exhausted", "quota exceeded", "429")

logger = logging.getLogger(__name__)
_MODEL_BACKPRESSURE_UNTIL: dict[str, float] = {}
_MODEL_BACKPRESSURE_REASON: dict[str, str] = {}
_MODEL_BACKPRESSURE_LOCK = threading.RLock()


def model_backpressure_message(model_name: str) -> str:
    with _MODEL_BACKPRESSURE_LOCK:
        until = _MODEL_BACKPRESSURE_UNTIL.get(model_name)
        if until is None:
            return ""
        now = time.monotonic()
        if now >= until:
            _MODEL_BACKPRESSURE_UNTIL.pop(model_name, None)
            _MODEL_BACKPRESSURE_REASON.pop(model_name, None)
            return ""
        remaining = max(1, int(until - now))
        reason = _MODEL_BACKPRESSURE_REASON.get(model_name, "temporary provider backpressure")
        return f"{reason}; retry in ~{remaining}s"


def maybe_apply_model_backpressure(
    *,
    model_name: str,
    error: str,
    parse_model_ref: Callable[[str], tuple[str, str]],
    safe_env_int: Callable[[str, int], int],
) -> None:
    provider, _ = parse_model_ref(model_name)
    if provider != "gemini":
        return

    message = error.lower()
    cooldown_seconds = 0
    reason = ""

    if any(pattern in message for pattern in GEMINI_MISSING_KEY_PATTERNS):
        cooldown_seconds = safe_env_int(
            "GEMINI_MISSING_KEY_BACKPRESSURE_SECONDS",
            DEFAULT_GEMINI_MISSING_KEY_BACKPRESSURE_SECONDS,
        )
        reason = "missing GOOGLE_API_KEY for gemini route"
    elif any(pattern in message for pattern in GEMINI_QUOTA_PATTERNS):
        cooldown_seconds = safe_env_int(
            "GEMINI_QUOTA_BACKPRESSURE_SECONDS",
            DEFAULT_GEMINI_QUOTA_BACKPRESSURE_SECONDS,
        )
        reason = "gemini quota/rate-limit backpressure"

    if cooldown_seconds <= 0:
        return

    until = time.monotonic() + cooldown_seconds
    with _MODEL_BACKPRESSURE_LOCK:
        existing_until = _MODEL_BACKPRESSURE_UNTIL.get(model_name, 0.0)
        if until <= existing_until:
            return
        _MODEL_BACKPRESSURE_UNTIL[model_name] = until
        _MODEL_BACKPRESSURE_REASON[model_name] = reason
    logger.warning(
        "Backpressure enabled for model '%s' for %ss (%s)",
        model_name,
        cooldown_seconds,
        reason,
    )
