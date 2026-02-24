"""Shared pipeline trace helpers."""
import json
import logging
import time
from typing import Any

logger = logging.getLogger("daily_blog.trace")


def trace_enabled() -> bool:
    from daily_blog.core.env_parsing import env_bool

    return env_bool("PIPELINE_TRACE", False)


def trace_event(event: str, **fields: Any) -> None:
    if not trace_enabled():
        return
    payload = {"event": event, "ts": time.time(), **fields}
    try:
        logger.info("TRACE %s", json.dumps(payload, ensure_ascii=True, sort_keys=True))
    except Exception:  # noqa: BLE001
        logger.info("TRACE %s", payload)
