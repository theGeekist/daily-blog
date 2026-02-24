import logging
import os
import signal
import subprocess
import threading
import time
from typing import Any, Callable

from daily_blog.core.env_parsing import env_bool, env_int
from daily_blog.model_inference.errors import ModelCallError
from daily_blog.model_inference.schema import sanitize_gemini_schema

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_GEMINI_TIMEOUT_SECONDS = 45
DEFAULT_GEMINI_CLI_TIMEOUT_SECONDS = 30
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 75
DEFAULT_MODEL_CLI_TIMEOUT_SECONDS = 60


def parse_model_ref(model_name: str) -> tuple[str, str]:
    if model_name == "deterministic-code":
        raise ModelCallError("deterministic-code is not invokable via call_model")

    if ":" in model_name:
        provider, model_id = model_name.split(":", 1)
        if provider in {"ollama", "gemini", "gemini-cli", "opencode", "openclaw"}:
            return provider, model_id

    if "/" in model_name:
        provider, model_id = model_name.split("/", 1)
        if provider in {"ollama", "gemini", "gemini-cli", "opencode", "openclaw"}:
            return provider, model_id

    return "opencode", model_name


def dispatch_model(model_name: str, prompt: str, schema: dict | None) -> str:
    provider, model_id = parse_model_ref(model_name)
    dispatch_map: dict[str, Callable[[str, str, dict | None], str]] = {
        "ollama": dispatch_ollama,
        "gemini": dispatch_gemini,
        "gemini-cli": dispatch_gemini_cli,
        "opencode": dispatch_opencode,
        "openclaw": dispatch_openclaw,
    }
    dispatcher = dispatch_map.get(provider)
    if dispatcher is None:
        raise ModelCallError(f"Unsupported provider '{provider}' for model '{model_name}'")
    return dispatcher(model_name, prompt, schema)


def dispatch_ollama(model_name: str, prompt: str, schema: dict | None) -> str:
    try:
        from ollama import chat
    except ImportError as exc:
        raise ModelCallError(
            "Missing dependency 'ollama'. Install project dependencies before using ollama routes."
        ) from exc

    provider, model_id = parse_model_ref(model_name)
    if provider != "ollama":
        raise ModelCallError(f"Invalid ollama model route '{model_name}'")

    kwargs: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
    }
    if schema:
        kwargs["format"] = schema

    timeout_seconds = env_int("OLLAMA_TIMEOUT_SECONDS", DEFAULT_OLLAMA_TIMEOUT_SECONDS)

    try:
        resp = run_with_timeout(
            lambda: chat(**kwargs),
            timeout_seconds=max(1, timeout_seconds),
            label=f"ollama '{model_id}'",
        )
    except TypeError as exc:
        if schema and "format" in kwargs:
            logger.warning(
                "Ollama client rejected schema format; retrying without schema "
                "enforcement at provider layer"
            )
            kwargs.pop("format", None)
            try:
                resp = run_with_timeout(
                    lambda: chat(**kwargs),
                    timeout_seconds=max(1, timeout_seconds),
                    label=f"ollama '{model_id}'",
                )
            except Exception as retry_exc:  # noqa: BLE001
                raise ModelCallError(
                    f"Ollama SDK call failed for model '{model_name}': {retry_exc}"
                ) from retry_exc
        else:
            raise ModelCallError(f"Ollama SDK call failed for model '{model_name}': {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ModelCallError(f"Ollama SDK call failed for model '{model_name}': {exc}") from exc

    content = str(getattr(getattr(resp, "message", None), "content", "") or "").strip()
    if not content:
        raise ModelCallError(f"Ollama returned empty output for model '{model_name}'")
    return content


def dispatch_gemini(model_name: str, prompt: str, schema: dict | None) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ModelCallError(
            "Missing dependency 'google-genai'. Install project dependencies for Gemini routes."
        ) from exc

    use_vertex = env_bool("GOOGLE_GENAI_USE_VERTEXAI", False)
    if use_vertex:
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        if not project:
            raise ModelCallError(
                "GOOGLE_CLOUD_PROJECT is required when GOOGLE_GENAI_USE_VERTEXAI=1"
            )
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "").strip() or "us-central1"
        client = genai.Client(vertexai=True, project=project, location=location)
    else:
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        if not api_key:
            raise ModelCallError(
                "GOOGLE_API_KEY is required for gemini routes "
                "(or set GOOGLE_GENAI_USE_VERTEXAI=1 to use Vertex AI ADC)"
            )
        client = genai.Client(api_key=api_key)

    provider, model_id = parse_model_ref(model_name)
    if provider != "gemini":
        raise ModelCallError(f"Invalid gemini model route '{model_name}'")

    generation_config: types.GenerateContentConfig | None = None
    if schema:
        generation_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=sanitize_gemini_schema(schema),
        )

    timeout_seconds = env_int("GEMINI_TIMEOUT_SECONDS", DEFAULT_GEMINI_TIMEOUT_SECONDS)
    try:
        resp = run_with_timeout(
            lambda: client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=generation_config,
            ),
            timeout_seconds=max(1, timeout_seconds),
            label=f"gemini '{model_id}'",
        )
    except Exception as exc:  # noqa: BLE001
        raise ModelCallError(f"Gemini SDK call failed for model '{model_name}': {exc}") from exc

    content = str(getattr(resp, "text", "") or "").strip()
    if not content:
        raise ModelCallError(f"Gemini returned empty output for model '{model_name}'")
    return content


def dispatch_gemini_cli(model_name: str, prompt: str, schema: dict | None) -> str:
    if schema is not None:
        logger.warning(
            "Schema not enforced for gemini-cli provider; "
            "relying on prompt and post-parse validation"
        )
    provider, model_id = parse_model_ref(model_name)
    if provider != "gemini-cli":
        raise ModelCallError(f"Invalid gemini-cli model route '{model_name}'")

    command = ["gemini", "--model", model_id, "--output-format", "text"]
    timeout_seconds = env_int("GEMINI_CLI_TIMEOUT_SECONDS", DEFAULT_GEMINI_CLI_TIMEOUT_SECONDS)
    completed = run_subprocess_model_with_kill(
        command=command,
        prompt=prompt,
        timeout_seconds=max(1, timeout_seconds),
        cli_tool="gemini",
        cli_model=model_id,
    )

    output = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    combined = "\n".join(part for part in (output, stderr) if part)
    if completed.returncode != 0:
        raise ModelCallError(
            f"Gemini CLI returned non-zero status {completed.returncode} for model '{model_id}'. "
            f"Output: {combined or '<empty>'}"
        )
    if not output:
        raise ModelCallError(f"Gemini CLI returned empty output for model '{model_id}'")
    return output


def dispatch_opencode(model_name: str, prompt: str, schema: dict | None) -> str:
    if schema is not None:
        logger.warning(
            "Schema not enforced for opencode provider; relying on prompt and post-parse validation"
        )
    provider, model_id = parse_model_ref(model_name)
    if provider != "opencode":
        raise ModelCallError(f"Invalid opencode model route '{model_name}'")
    return run_subprocess_model("opencode", model_id, prompt)


def dispatch_openclaw(model_name: str, prompt: str, schema: dict | None) -> str:
    if schema is not None:
        logger.warning(
            "Schema not enforced for openclaw provider; relying on prompt and post-parse validation"
        )
    provider, model_id = parse_model_ref(model_name)
    if provider != "openclaw":
        raise ModelCallError(f"Invalid openclaw model route '{model_name}'")
    return run_subprocess_model("openclaw", model_id, prompt)


def run_subprocess_model(cli_tool: str, cli_model: str, prompt: str) -> str:
    command = [cli_tool, "run", "-m", cli_model]
    timeout_seconds = env_int("MODEL_CLI_TIMEOUT_SECONDS", DEFAULT_MODEL_CLI_TIMEOUT_SECONDS)
    completed = run_subprocess_model_with_kill(
        command=command,
        prompt=prompt,
        timeout_seconds=max(1, timeout_seconds),
        cli_tool=cli_tool,
        cli_model=cli_model,
    )

    output = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    combined = "\n".join(part for part in (output, stderr) if part)

    if completed.returncode != 0:
        raise ModelCallError(
            f"CLI returned non-zero status {completed.returncode} for model '{cli_model}'. "
            f"Output: {combined or '<empty>'}"
        )

    if not combined:
        raise ModelCallError(f"CLI returned empty output for model '{cli_model}'")

    return output


def run_subprocess_model_with_kill(
    *,
    command: list[str],
    prompt: str,
    timeout_seconds: int,
    cli_tool: str,
    cli_model: str,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise ModelCallError(f"CLI tool not found: {cli_tool}") from exc

    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        kill_process_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except Exception:  # noqa: BLE001
            stdout, stderr = ("", "")
        raise ModelCallError(
            f"CLI call timed out after {timeout_seconds}s for model '{cli_model}'"
        ) from exc

    return subprocess.CompletedProcess(
        args=command,
        returncode=proc.returncode or 0,
        stdout=stdout,
        stderr=stderr,
    )


def kill_process_tree(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def run_with_timeout(call: Callable[[], Any], *, timeout_seconds: int, label: str) -> Any:
    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result["value"] = call()
        except BaseException as exc:  # noqa: BLE001
            error["exc"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=max(1, timeout_seconds))
    if thread.is_alive():
        raise ModelCallError(f"{label} call timed out after {timeout_seconds}s")
    if "exc" in error:
        raise error["exc"]
    return result.get("value")
