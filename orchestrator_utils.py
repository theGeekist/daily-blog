#!/usr/bin/env python3
import json
import logging
import os
import re
import subprocess
import time
from json import JSONDecodeError
from json.decoder import JSONDecoder
from pathlib import Path
from typing import Any, Callable

DEFAULT_MODEL_ROUTING_PATH = Path(__file__).resolve().parent / "config" / "model-routing.json"
DEFAULT_PROMPTS_PATH = Path(__file__).resolve().parent / "config" / "prompts.json"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_SCHEMA_RETRIES = 2
DEFAULT_GEMINI_QUOTA_BACKPRESSURE_SECONDS = 300
DEFAULT_GEMINI_MISSING_KEY_BACKPRESSURE_SECONDS = 1800

logger = logging.getLogger(__name__)
_MODEL_BACKPRESSURE_UNTIL: dict[str, float] = {}
_MODEL_BACKPRESSURE_REASON: dict[str, str] = {}


class ModelCallError(RuntimeError):
    pass


class ModelOutputValidationError(ModelCallError):
    pass


def call_model(stage_name: str, prompt: str, schema: dict | None = None) -> dict[str, Any]:
    routing_path = Path(os.getenv("MODEL_ROUTING_CONFIG", str(DEFAULT_MODEL_ROUTING_PATH)))
    prompts_path = Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS_PATH)))
    routing = _load_model_routing(routing_path)
    prompt = _apply_prompt_overrides(
        stage_name=stage_name,
        prompt=prompt,
        prompts_path=prompts_path,
    )
    stage_config = routing.get(stage_name)
    if not isinstance(stage_config, dict):
        raise ModelCallError(f"Stage '{stage_name}' not found in {routing_path}")

    candidates = _candidate_models(stage_config)

    if not candidates:
        raise ModelCallError(f"Stage '{stage_name}' has no usable primary/fallback model")

    failures: list[str] = []

    for model_name in candidates:
        blocked_message = _model_backpressure_message(model_name)
        if blocked_message:
            failures.append(f"{model_name}: ModelCallError: {blocked_message}")
            logger.warning(
                "Skipping model '%s' for stage '%s' due to backpressure: %s",
                model_name,
                stage_name,
                blocked_message,
            )
            continue
        try:
            parsed_content = _invoke_with_retries(
                model_name=model_name,
                prompt=prompt,
                schema=schema,
                retries=DEFAULT_SCHEMA_RETRIES,
            )
            return {"content": parsed_content, "model_used": model_name}
        except Exception as exc:  # noqa: BLE001
            message = f"{model_name}: {type(exc).__name__}: {exc}"
            failures.append(message)
            logger.warning("Model invocation failed for stage '%s': %s", stage_name, message)
            _maybe_apply_model_backpressure(model_name=model_name, error=str(exc))

    joined_failures = " | ".join(failures)
    raise ModelCallError(
        "All models failed for stage "
        f"'{stage_name}' (primary then fallback). Details: {joined_failures}"
    )


def _candidate_models(stage_config: dict[str, Any]) -> list[str]:
    primary = stage_config.get("primary")
    fallback = stage_config.get("fallback")
    fallbacks = stage_config.get("fallbacks")

    candidates: list[str] = []
    for model in (primary, fallback):
        if isinstance(model, str) and model.strip():
            candidates.append(model.strip())
    if isinstance(fallbacks, list):
        for model in fallbacks:
            if isinstance(model, str) and model.strip():
                candidates.append(model.strip())

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(candidates))


def _invoke_with_retries(
    model_name: str,
    prompt: str,
    schema: dict | None,
    retries: int,
) -> Any:
    last_error: ModelOutputValidationError | None = None
    for attempt in range(retries + 1):
        try:
            raw_output = _dispatch_model(model_name=model_name, prompt=prompt, schema=schema)
        except ModelCallError:
            # Hard provider/transport failures should not be retried.
            raise
        try:
            parsed_content = _extract_json_payload(raw_output)
            if schema is not None:
                _validate_schema(parsed_content, schema)
            return parsed_content
        except ModelOutputValidationError as exc:
            last_error = exc
            if attempt >= retries:
                break
            logger.info(
                "Retrying model after parse/schema failure",
                extra={"model": model_name, "attempt": attempt + 1},
            )

    if last_error is None:
        raise ModelCallError(f"Unknown model invocation failure for '{model_name}'")
    raise last_error


def _dispatch_model(model_name: str, prompt: str, schema: dict | None) -> str:
    provider, model_id = _parse_model_ref(model_name)
    dispatch_map: dict[str, Callable[[str, str, dict | None], str]] = {
        "ollama": _dispatch_ollama,
        "gemini": _dispatch_gemini,
        "gemini-cli": _dispatch_gemini_cli,
        "opencode": _dispatch_opencode,
        "openclaw": _dispatch_openclaw,
    }
    dispatcher = dispatch_map.get(provider)
    if dispatcher is None:
        raise ModelCallError(f"Unsupported provider '{provider}' for model '{model_name}'")
    return dispatcher(model_name, prompt, schema)


def _parse_model_ref(model_name: str) -> tuple[str, str]:
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


def _dispatch_ollama(model_name: str, prompt: str, schema: dict | None) -> str:
    try:
        from ollama import chat
    except ImportError as exc:
        raise ModelCallError(
            "Missing dependency 'ollama'. Install project dependencies before using ollama routes."
        ) from exc

    provider, model_id = _parse_model_ref(model_name)
    if provider != "ollama":
        raise ModelCallError(f"Invalid ollama model route '{model_name}'")

    kwargs: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
    }
    if schema:
        kwargs["format"] = schema

    try:
        resp = chat(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise ModelCallError(f"Ollama SDK call failed for model '{model_name}': {exc}") from exc

    content = str(getattr(getattr(resp, "message", None), "content", "") or "").strip()
    if not content:
        raise ModelCallError(f"Ollama returned empty output for model '{model_name}'")
    return content


def _dispatch_gemini(model_name: str, prompt: str, schema: dict | None) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ModelCallError(
            "Missing dependency 'google-genai'. Install project dependencies for Gemini routes."
        ) from exc

    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "0") == "1"
    if use_vertex:
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        if not project:
            raise ModelCallError(
                "GOOGLE_CLOUD_PROJECT is required when GOOGLE_GENAI_USE_VERTEXAI=1"
            )
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "").strip() or "us-central1"
        client = genai.Client(vertexai=True, project=project, location=location)
        logger.debug(
            "Using Vertex AI ADC for Gemini route '%s' (project=%s, location=%s)",
            model_name,
            project,
            location,
        )
    else:
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        if not api_key:
            raise ModelCallError(
                "GOOGLE_API_KEY is required for gemini routes "
                "(or set GOOGLE_GENAI_USE_VERTEXAI=1 to use Vertex AI ADC)"
            )
        client = genai.Client(api_key=api_key)

    provider, model_id = _parse_model_ref(model_name)
    if provider != "gemini":
        raise ModelCallError(f"Invalid gemini model route '{model_name}'")

    generation_config: types.GenerateContentConfig | None = None
    if schema:
        sanitized_schema = _sanitize_gemini_schema(schema)
        logger.debug("Sending sanitized schema to Gemini: %s", sanitized_schema)
        generation_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=sanitized_schema,
        )

    try:
        resp = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=generation_config,
        )
    except Exception as exc:  # noqa: BLE001
        raise ModelCallError(f"Gemini SDK call failed for model '{model_name}': {exc}") from exc

    content = str(getattr(resp, "text", "") or "").strip()
    if not content:
        raise ModelCallError(f"Gemini returned empty output for model '{model_name}'")
    return content


def _dispatch_gemini_cli(model_name: str, prompt: str, schema: dict | None) -> str:
    if schema is not None:
        logger.warning(
            "Schema not enforced for gemini-cli provider; "
            "relying on prompt and post-parse validation"
        )
    provider, model_id = _parse_model_ref(model_name)
    if provider != "gemini-cli":
        raise ModelCallError(f"Invalid gemini-cli model route '{model_name}'")

    command = [
        "gemini",
        "--model",
        model_id,
        "--prompt",
        prompt,
        "--output-format",
        "text",
    ]
    logger.info("Calling model via Gemini CLI", extra={"model": model_id})

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ModelCallError("CLI tool not found: gemini") from exc
    except subprocess.TimeoutExpired as exc:
        raise ModelCallError(
            f"CLI call timed out after {DEFAULT_TIMEOUT_SECONDS}s for model '{model_id}'"
        ) from exc

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


def _sanitize_gemini_schema(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            # Gemini schema support is strict; strip pydantic decoration keys.
            if key in {"title", "examples", "default"}:
                continue
            cleaned[key] = _sanitize_gemini_schema(child)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_gemini_schema(item) for item in value]
    return value


def _dispatch_opencode(model_name: str, prompt: str, schema: dict | None) -> str:
    if schema is not None:
        logger.warning(
            "Schema not enforced for opencode provider; relying on prompt and post-parse validation"
        )
    provider, model_id = _parse_model_ref(model_name)
    if provider != "opencode":
        raise ModelCallError(f"Invalid opencode model route '{model_name}'")
    return _run_subprocess_model("opencode", model_id, prompt)


def _dispatch_openclaw(model_name: str, prompt: str, schema: dict | None) -> str:
    if schema is not None:
        logger.warning(
            "Schema not enforced for openclaw provider; relying on prompt and post-parse validation"
        )
    provider, model_id = _parse_model_ref(model_name)
    if provider != "openclaw":
        raise ModelCallError(f"Invalid openclaw model route '{model_name}'")
    return _run_subprocess_model("openclaw", model_id, prompt)


def _run_subprocess_model(cli_tool: str, cli_model: str, prompt: str) -> str:
    command = [cli_tool, "run", "-m", cli_model, prompt]
    logger.info("Calling model via CLI", extra={"cli": cli_tool, "model": cli_model})

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ModelCallError(f"CLI tool not found: {cli_tool}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ModelCallError(
            f"CLI call timed out after {DEFAULT_TIMEOUT_SECONDS}s for model '{cli_model}'"
        ) from exc

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

    return combined


def _load_model_routing(config_path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelCallError(f"Model routing file not found: {config_path}") from exc
    except JSONDecodeError as exc:
        raise ModelCallError(f"Invalid JSON in model routing file: {config_path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ModelCallError(f"Model routing file must contain an object: {config_path}")
    return loaded


def _load_prompt_overrides(config_path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _apply_prompt_overrides(stage_name: str, prompt: str, prompts_path: Path | None = None) -> str:
    prompts = _load_prompt_overrides(prompts_path or DEFAULT_PROMPTS_PATH)
    stage = prompts.get(stage_name)
    if not isinstance(stage, dict):
        return prompt
    template = stage.get("template")
    prefix = stage.get("prefix")
    suffix = stage.get("suffix")
    if isinstance(template, str) and "{prompt}" in template:
        rendered = template.replace("{prompt}", prompt)
    else:
        rendered = prompt
    if isinstance(prefix, str) and prefix.strip():
        rendered = f"{prefix.strip()}\n\n{rendered}"
    if isinstance(suffix, str) and suffix.strip():
        rendered = f"{rendered}\n\n{suffix.strip()}"
    return rendered


def _extract_json_payload(text: str) -> Any:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.DOTALL)
    if fenced:
        return _unwrap_single_object_array(json.loads(fenced.group(1)))

    decoder = JSONDecoder()
    for idx, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[idx:])
            return _unwrap_single_object_array(value)
        except JSONDecodeError:
            continue

    raise ModelOutputValidationError("No valid JSON object/array found in model output")


def _unwrap_single_object_array(value: Any) -> Any:
    """Unwrap ``[{...}]`` to ``{...}`` for models that wrap object payloads in an array."""
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        logger.debug("Unwrapping single-item array from model output")
        return value[0]
    return value


def _validate_schema(instance: Any, schema: dict[str, Any]) -> None:
    _validate_node(instance=instance, schema=schema, path="$")


def _validate_node(instance: Any, schema: dict[str, Any], path: str) -> None:
    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        _assert_type(instance=instance, expected=expected_type, path=path)

    if expected_type == "object":
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in instance:
                    raise ModelOutputValidationError(
                        f"Schema validation failed at {path}: missing '{key}'"
                    )

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in instance and isinstance(child_schema, dict):
                    _validate_node(instance[key], child_schema, f"{path}.{key}")

    if expected_type == "array":
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(instance):
                _validate_node(item, item_schema, f"{path}[{idx}]")

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and instance not in enum_values:
        raise ModelOutputValidationError(
            f"Schema validation failed at {path}: value {instance!r} not in enum {enum_values!r}"
        )


def _assert_type(instance: Any, expected: str, path: str) -> None:
    type_checks: dict[str, Any] = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }

    check = type_checks.get(expected)
    if check is None:
        raise ModelOutputValidationError(f"Unsupported schema type '{expected}' at {path}")
    if not check(instance):
        raise ModelOutputValidationError(
            "Schema validation failed at "
            f"{path}: expected {expected}, got {type(instance).__name__}"
        )


def _model_backpressure_message(model_name: str) -> str:
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


def _maybe_apply_model_backpressure(model_name: str, error: str) -> None:
    provider, _ = _parse_model_ref(model_name)
    if provider != "gemini":
        return

    message = error.lower()
    cooldown_seconds = 0
    reason = ""

    if "google_api_key is required" in message:
        cooldown_seconds = int(
            os.getenv(
                "GEMINI_MISSING_KEY_BACKPRESSURE_SECONDS",
                str(DEFAULT_GEMINI_MISSING_KEY_BACKPRESSURE_SECONDS),
            )
        )
        reason = "missing GOOGLE_API_KEY for gemini route"
    elif "resource_exhausted" in message or "quota exceeded" in message or "429" in message:
        cooldown_seconds = int(
            os.getenv(
                "GEMINI_QUOTA_BACKPRESSURE_SECONDS",
                str(DEFAULT_GEMINI_QUOTA_BACKPRESSURE_SECONDS),
            )
        )
        reason = "gemini quota/rate-limit backpressure"

    if cooldown_seconds <= 0:
        return

    until = time.monotonic() + cooldown_seconds
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
