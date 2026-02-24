from __future__ import annotations

import time


def elapsed_ms(started_at: float) -> int:
    return max(1, int((time.monotonic() - started_at) * 1000))


def emit_progress(stage: str, event: str, /, **fields: object) -> None:
    """Emit a stable, parseable single-line progress event to stdout."""
    parts = [f"[{stage}]", event]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    print(" ".join(parts), flush=True)
