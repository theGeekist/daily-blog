import os
import re
import subprocess
import threading
import time
import traceback
from typing import Any


def _canonical_model_name(model_name: str) -> str:
    normalized = model_name.strip()
    if not normalized:
        return "unknown"
    if normalized.startswith("opencode:"):
        return f"opencode/{normalized.split(':', 1)[1]}"
    if normalized.startswith("openclaw:"):
        return f"openclaw/{normalized.split(':', 1)[1]}"
    if normalized.startswith("ollama:"):
        return f"ollama/{normalized.split(':', 1)[1]}"
    if ":" in normalized and "/" not in normalized:
        provider, model = normalized.split(":", 1)
        if provider and model:
            return f"{provider}/{model}"
    if normalized.startswith("openclaw/") or normalized.startswith("opencode/"):
        return normalized
    if "/" in normalized:
        return normalized
    return f"opencode/{normalized}"


def _extract_model_from_output(output: str, fallback_model: str) -> str:
    if not output:
        return fallback_model

    keyed = re.search(r'"model_used"\s*:\s*"([^"]+)"', output)
    if keyed:
        return _canonical_model_name(keyed.group(1))

    for pattern in (
        r"\b(?:opencode|openclaw|ollama)/[A-Za-z0-9_.:-]+\b",
        r"\b(?:opencode|openclaw|ollama):[A-Za-z0-9_.-]+\b",
        r"\bmodel\s*[=:]\s*([A-Za-z0-9_.:/-]+)",
    ):
        match = re.search(pattern, output, flags=re.IGNORECASE)
        if not match:
            continue
        token = match.group(1) if match.groups() else match.group(0)
        return _canonical_model_name(token)

    return fallback_model


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


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

        env = os.environ.copy()
        env["RUN_ID"] = run_id
        env["PIPELINE_RUN_ID"] = run_id
        env["MODEL_ROUTE"] = route_used
        env["MODEL_NAME"] = routed_model
        env["MODEL_ROUTING_STAGE"] = stage_route_key

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
            if attempt <= retries:
                time.sleep(2**attempt)
            continue

        combined_output = "\n".join(
            part.strip() for part in (proc.stdout or "", proc.stderr or "") if part and part.strip()
        )
        last_output = combined_output
        if proc.returncode == 0:
            detected_model = _extract_model_from_output(combined_output, routed_model)
            return True, combined_output, "", route_used, detected_model
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
    if not last_error:
        last_error = "unknown error"
    if not last_output:
        last_output = last_error
    return False, last_output, last_error, last_route_used, last_model_used


def _run_subprocess_with_heartbeat(
    *,
    stage_name: str,
    attempt: int,
    total_attempts: int,
    command: list[str],
    timeout_seconds: int,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    heartbeat_seconds = 15
    started = time.time()
    result: dict[str, Any] = {"proc": None, "error": None}

    def _target() -> None:
        try:
            result["proc"] = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except Exception as exc:  # pragma: no cover - exercised via caller behavior
            result["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()

    while thread.is_alive():
        thread.join(timeout=heartbeat_seconds)
        if thread.is_alive():
            elapsed = int(time.time() - started)
            print(
                f"[{stage_name}] Attempt {attempt}/{total_attempts} still running... "
                f"elapsed={elapsed}s"
            )

    error = result.get("error")
    if error is not None:
        raise error

    proc = result.get("proc")
    if proc is None:  # pragma: no cover - defensive
        raise RuntimeError("subprocess finished without result")
    return proc
