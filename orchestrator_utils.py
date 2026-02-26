#!/usr/bin/env python3
import json
import logging
import re
import subprocess
from json import JSONDecodeError
from json.decoder import JSONDecoder
from pathlib import Path
from typing import Any

DEFAULT_MODEL_ROUTING_PATH = Path(__file__).resolve().parent / "config" / "model-routing.json"
DEFAULT_PROMPTS_PATH = Path(__file__).resolve().parent / "config" / "prompts.json"
DEFAULT_TIMEOUT_SECONDS = 120

logger = logging.getLogger(__name__)


class ModelCallError(RuntimeError):
    pass


def call_model(stage_name: str, prompt: str, schema: dict | None = None) -> dict[str, Any]:
    routing = _load_model_routing(DEFAULT_MODEL_ROUTING_PATH)
    prompt = _apply_prompt_overrides(stage_name=stage_name, prompt=prompt)
    stage_config = routing.get(stage_name)
    if not isinstance(stage_config, dict):
        raise ModelCallError(f"Stage '{stage_name}' not found in {DEFAULT_MODEL_ROUTING_PATH}")

    candidates = _candidate_models(stage_config)

    if not candidates:
        raise ModelCallError(
            f"Stage '{stage_name}' has no usable primary/fallback/fallbacks model entries"
        )

    failures: list[str] = []

    for model_name in candidates:
        try:
            raw_output = _run_model_cli(model_name=model_name, prompt=prompt)
            parsed_content = _extract_json_payload(raw_output)
            if schema is not None:
                _validate_schema(parsed_content, schema)
            return {"content": parsed_content, "model_used": model_name}
        except Exception as exc:  # noqa: BLE001
            message = f"{model_name}: {type(exc).__name__}: {exc}"
            failures.append(message)
            logger.warning("Model invocation failed for stage '%s': %s", stage_name, message)

    joined_failures = " | ".join(failures)
    raise ModelCallError(
        "All models failed for stage "
        f"'{stage_name}' (primary then fallback chain). Details: {joined_failures}"
    )


def _candidate_models(stage_config: dict[str, Any]) -> list[str]:
    primary = stage_config.get("primary")
    fallback = stage_config.get("fallback")
    fallbacks = stage_config.get("fallbacks")

    candidates: list[str] = []
    for model in (primary, fallback):
        if isinstance(model, str) and model.strip():
            candidates.append(model.strip())

    if isinstance(fallbacks, str):
        if fallbacks.strip():
            candidates.append(fallbacks.strip())
    elif isinstance(fallbacks, list):
        for model in fallbacks:
            if isinstance(model, str) and model.strip():
                candidates.append(model.strip())

    # Preserve order and dedupe.
    return list(dict.fromkeys(candidates))


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


def _apply_prompt_overrides(stage_name: str, prompt: str) -> str:
    prompts = _load_prompt_overrides(DEFAULT_PROMPTS_PATH)
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


def _resolve_cli(model_name: str) -> tuple[str, str]:
    if model_name.startswith("openclaw:"):
        return "openclaw", model_name.split(":", 1)[1]
    if model_name.startswith("opencode:"):
        return "opencode", model_name.split(":", 1)[1]
    if model_name.startswith("ollama:"):
        return "ollama", model_name.split(":", 1)[1]
    if model_name.startswith("openclaw/"):
        return "openclaw", model_name.split("/", 1)[1]
    if model_name.startswith("ollama/"):
        return "ollama", model_name.split("/", 1)[1]
    return "opencode", model_name


def _run_model_cli(model_name: str, prompt: str) -> str:
    cli_tool, cli_model = _resolve_cli(model_name)
    if cli_tool == "ollama":
        command = [cli_tool, "run", cli_model, prompt]
    else:
        command = [cli_tool, "run", "-m", cli_model, prompt]
    logger.info("Calling model via CLI", extra={"cli": cli_tool, "model": model_name})

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
            f"CLI call timed out after {DEFAULT_TIMEOUT_SECONDS}s for model '{model_name}'"
        ) from exc

    output = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    combined = "\n".join(part for part in (output, stderr) if part)

    if completed.returncode != 0:
        raise ModelCallError(
            f"CLI returned non-zero status {completed.returncode} for model '{model_name}'. "
            f"Output: {combined or '<empty>'}"
        )

    if not combined:
        raise ModelCallError(f"CLI returned empty output for model '{model_name}'")

    return combined


def _extract_json_payload(text: str) -> Any:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    decoder = JSONDecoder()
    for idx, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[idx:])
            return value
        except JSONDecodeError:
            continue

    raise ModelCallError("No valid JSON object/array found in CLI output")


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
                    raise ModelCallError(f"Schema validation failed at {path}: missing '{key}'")

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
        raise ModelCallError(
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
        raise ModelCallError(f"Unsupported schema type '{expected}' at {path}")
    if not check(instance):
        raise ModelCallError(
            "Schema validation failed at "
            f"{path}: expected {expected}, got {type(instance).__name__}"
        )
