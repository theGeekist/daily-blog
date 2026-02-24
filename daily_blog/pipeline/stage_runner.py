import os
import subprocess
import time
import traceback
from typing import Any

from daily_blog.core.tracing import trace_enabled as _trace_enabled  # noqa: F401
from daily_blog.core.tracing import trace_event as _trace_event
from daily_blog.pipeline.subprocess_runner import (
    _canonical_model_name,
    _coerce_text,
    _extract_model_from_output,
    _run_subprocess_with_heartbeat,
    _stream_subprocess_output,
)


def _build_error_context(
    *,
    stage_name: str,
    command: list[str],
    attempt: int,
    total_attempts: int,
    route_used: str,
    model_used: str,
    timeout_seconds: int,
    returncode: int | None,
    stdout: str,
    stderr: str,
    exception: Exception | None = None,
) -> str:
    details = [
        f"stage={stage_name}",
        f"attempt={attempt}/{total_attempts}",
        f"route={route_used}",
        f"model={model_used}",
        f"timeout_seconds={timeout_seconds}",
        f"command={' '.join(command)}",
    ]
    if returncode is not None:
        details.append(f"returncode={returncode}")
    if stdout.strip():
        details.append(f"stdout={stdout.strip()}")
    if stderr.strip():
        details.append(f"stderr={stderr.strip()}")
    if exception is not None:
        details.append("traceback=" + "".join(traceback.format_exception(exception)).strip())
    return " | ".join(details)


def _resolve_route_for_attempt(
    routing: dict[str, Any],
    stage_route_key: str,
    default_model: str,
    attempt: int,
) -> tuple[str, str]:
    stage_routes = routing.get(stage_route_key, {}) if isinstance(routing, dict) else {}
    primary = stage_routes.get("primary") if isinstance(stage_routes, dict) else None
    fallback = stage_routes.get("fallback") if isinstance(stage_routes, dict) else None

    primary_name = primary if isinstance(primary, str) and primary.strip() else default_model
    fallback_name = fallback if isinstance(fallback, str) and fallback.strip() else primary_name
    if attempt == 1:
        return "primary", _canonical_model_name(primary_name)
    return "fallback", _canonical_model_name(fallback_name)


def run_stage(
    stage_name: str,
    command: list[str],
    retries: int,
    timeout_seconds: int,
    routing: dict[str, Any],
    stage_route_key: str,
    default_model: str,
    run_id: str,
) -> tuple[bool, str, str, str, str]:
    last_error = ""
    last_output = ""
    last_route_used = "primary"
    last_model_used = _canonical_model_name(default_model)
    total_attempts = retries + 1

    for attempt in range(1, retries + 2):
        attempt_started = time.monotonic()
        route_used, routed_model = _resolve_route_for_attempt(
            routing=routing,
            stage_route_key=stage_route_key,
            default_model=default_model,
            attempt=attempt,
        )
        last_route_used = route_used
        last_model_used = routed_model
        print(
            f"[{stage_name}] Attempt {attempt}/{total_attempts} "
            f"route={route_used} model={routed_model} timeout={timeout_seconds}s"
        )
        _trace_event(
            "stage_attempt_start",
            stage=stage_name,
            attempt=attempt,
            total_attempts=total_attempts,
            route=route_used,
            model=routed_model,
            timeout_seconds=timeout_seconds,
            command=command,
        )

        env = os.environ.copy()
        env["RUN_ID"] = run_id
        env["PIPELINE_RUN_ID"] = run_id
        env["MODEL_ROUTE"] = route_used
        env["MODEL_NAME"] = routed_model
        env["MODEL_ROUTING_STAGE"] = stage_route_key
        env["STAGE_TIMEOUT_SECONDS"] = str(timeout_seconds)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        try:
            proc = _run_subprocess_with_heartbeat(
                stage_name=stage_name,
                attempt=attempt,
                total_attempts=total_attempts,
                command=command,
                timeout_seconds=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            last_error = _build_error_context(
                stage_name=stage_name,
                command=command,
                attempt=attempt,
                total_attempts=total_attempts,
                route_used=route_used,
                model_used=routed_model,
                timeout_seconds=timeout_seconds,
                returncode=None,
                stdout=_coerce_text(exc.stdout),
                stderr=_coerce_text(exc.stderr),
                exception=exc,
            )
            _trace_event(
                "stage_attempt_timeout",
                stage=stage_name,
                attempt=attempt,
                route=route_used,
                model=routed_model,
                elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
                error_type=type(exc).__name__,
            )
            if attempt <= retries:
                time.sleep(2**attempt)
            continue

        combined_output = "\n".join(
            part.strip() for part in (proc.stdout or "", proc.stderr or "") if part and part.strip()
        )
        returned_output = "" if _stream_subprocess_output() else combined_output
        last_output = returned_output
        if proc.returncode == 0:
            detected_model = _extract_model_from_output(combined_output, routed_model)
            _trace_event(
                "stage_attempt_ok",
                stage=stage_name,
                attempt=attempt,
                route=route_used,
                model=detected_model,
                elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
            )
            return True, returned_output, "", route_used, detected_model
        last_error = _build_error_context(
            stage_name=stage_name,
            command=command,
            attempt=attempt,
            total_attempts=total_attempts,
            route_used=route_used,
            model_used=routed_model,
            timeout_seconds=timeout_seconds,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
        if attempt <= retries:
            time.sleep(2**attempt)
            _trace_event(
                "stage_attempt_retry_scheduled",
                stage=stage_name,
                attempt=attempt,
                route=route_used,
                model=routed_model,
                elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
            )
    if not last_error:
        last_error = "unknown error"
    if not last_output:
        last_output = last_error
    return False, last_output, last_error, last_route_used, last_model_used
