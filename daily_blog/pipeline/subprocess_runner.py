import re
import subprocess
import threading
import time
from queue import Empty, Queue
from typing import Any

from daily_blog.core.env_parsing import env_bool


def _stream_subprocess_output() -> bool:
    return env_bool("PIPELINE_STREAM_SUBPROCESS_OUTPUT", True)


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
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stream_queue: Queue[tuple[str, str | None]] = Queue()
    timed_out = False
    last_output_at = started

    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )

    def _reader(stream: Any, stream_name: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                stream_queue.put((stream_name, line))
        finally:
            stream_queue.put((stream_name, None))

    stdout_thread = threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True)
    stderr_thread = threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    stream_closed = {"stdout": False, "stderr": False}
    next_heartbeat_at = started + heartbeat_seconds
    timeout_at = started + timeout_seconds

    while True:
        now = time.time()
        if now >= timeout_at and proc.poll() is None:
            timed_out = True
            proc.kill()

        try:
            stream_name, payload = stream_queue.get(timeout=0.2)
            if payload is None:
                stream_closed[stream_name] = True
            else:
                last_output_at = now
                if stream_name == "stdout":
                    stdout_lines.append(payload)
                    print(payload.rstrip("\n"))
                else:
                    stderr_lines.append(payload)
        except Empty:
            pass

        if now >= next_heartbeat_at and proc.poll() is None:
            if (now - last_output_at) < heartbeat_seconds:
                next_heartbeat_at = now + heartbeat_seconds
                continue
            elapsed = int(now - started)
            print(
                f"[{stage_name}] Attempt {attempt}/{total_attempts} still running... "
                f"elapsed={elapsed}s"
            )
            next_heartbeat_at = now + heartbeat_seconds

        if proc.poll() is not None and all(stream_closed.values()):
            break

    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    returncode = proc.returncode if proc.returncode is not None else 1
    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)

    if timed_out:
        raise subprocess.TimeoutExpired(command, timeout_seconds, output=stdout, stderr=stderr)

    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
