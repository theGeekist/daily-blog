"""Model call orchestration — primary entry point for all model invocations."""
import logging
import os
import time
from pathlib import Path
from typing import Any

from daily_blog.core.env_parsing import env_int as _env_int
from daily_blog.core.tracing import trace_enabled as _trace_enabled  # noqa: F401
from daily_blog.core.tracing import trace_event as _trace_event
from daily_blog.model_inference.backpressure import (
    maybe_apply_model_backpressure,
    model_backpressure_message,
)
from daily_blog.model_inference.config import (
    apply_prompt_overrides as _apply_prompt_overrides,
)
from daily_blog.model_inference.config import (
    load_model_routing as _load_model_routing,
)
from daily_blog.model_inference.dispatch import (
    dispatch_gemini as _dispatch_gemini,  # noqa: F401
)
from daily_blog.model_inference.dispatch import (
    dispatch_gemini_cli as _dispatch_gemini_cli,  # noqa: F401
)
from daily_blog.model_inference.dispatch import (
    dispatch_model as _dispatch_model,
)
from daily_blog.model_inference.dispatch import (
    dispatch_ollama as _dispatch_ollama,  # noqa: F401
)
from daily_blog.model_inference.dispatch import (
    dispatch_openclaw as _dispatch_openclaw,  # noqa: F401
)
from daily_blog.model_inference.dispatch import (
    dispatch_opencode as _dispatch_opencode,  # noqa: F401
)
from daily_blog.model_inference.dispatch import (
    parse_model_ref as _parse_model_ref,
)
from daily_blog.model_inference.errors import (  # noqa: F401
    ModelCallError,
    ModelOutputValidationError,
)
from daily_blog.model_inference.schema import (
    extract_json_payload as _extract_json_payload,
)
from daily_blog.model_inference.schema import (
    sanitize_gemini_schema as _sanitize_gemini_schema,  # noqa: F401
)
from daily_blog.model_inference.schema import (
    validate_schema as _validate_schema,
)

# Config defaults relative to project root (two levels up from this file's package dir)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MODEL_ROUTING_PATH = _PROJECT_ROOT / "config" / "model-routing.json"
DEFAULT_PROMPTS_PATH = _PROJECT_ROOT / "config" / "prompts.json"
DEFAULT_SCHEMA_RETRIES = 2

logger = logging.getLogger(__name__)


def call_model(stage_name: str, prompt: str, schema: dict | None = None) -> dict[str, Any]:
    call_started = time.monotonic()
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
    _trace_event(
        "model_call_start",
        stage=stage_name,
        candidates=candidates,
        prompt_chars=len(prompt),
        schema=bool(schema),
        routing_path=str(routing_path),
    )

    for model_name in candidates:
        attempt_started = time.monotonic()
        blocked_message = model_backpressure_message(model_name)
        if blocked_message:
            failures.append(f"{model_name}: ModelCallError: {blocked_message}")
            logger.warning(
                "Skipping model '%s' for stage '%s' due to backpressure: %s",
                model_name,
                stage_name,
                blocked_message,
            )
            _trace_event(
                "model_attempt_skipped",
                stage=stage_name,
                model=model_name,
                reason=blocked_message,
                elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
            )
            continue

        try:
            parsed_content = _invoke_with_retries(
                model_name=model_name,
                prompt=prompt,
                schema=schema,
                retries=DEFAULT_SCHEMA_RETRIES,
            )
            _trace_event(
                "model_attempt_ok",
                stage=stage_name,
                model=model_name,
                elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
            )
            _trace_event(
                "model_call_ok",
                stage=stage_name,
                model=model_name,
                elapsed_ms=int((time.monotonic() - call_started) * 1000),
            )
            return {"content": parsed_content, "model_used": model_name}
        except Exception as exc:  # noqa: BLE001
            message = f"{model_name}: {type(exc).__name__}: {exc}"
            failures.append(message)
            logger.warning("Model invocation failed for stage '%s': %s", stage_name, message)
            _trace_event(
                "model_attempt_error",
                stage=stage_name,
                model=model_name,
                error_type=type(exc).__name__,
                error=str(exc),
                elapsed_ms=int((time.monotonic() - attempt_started) * 1000),
            )
            maybe_apply_model_backpressure(
                model_name=model_name,
                error=str(exc),
                parse_model_ref=_parse_model_ref,
                safe_env_int=_env_int,
            )

    joined_failures = " | ".join(failures)
    _trace_event(
        "model_call_failed",
        stage=stage_name,
        elapsed_ms=int((time.monotonic() - call_started) * 1000),
        failures=failures,
    )
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

    return list(dict.fromkeys(candidates))


def _invoke_with_retries(model_name: str, prompt: str, schema: dict | None, retries: int) -> Any:
    last_error: ModelOutputValidationError | None = None
    for attempt in range(retries + 1):
        try:
            raw_output = _dispatch_model(model_name=model_name, prompt=prompt, schema=schema)
        except ModelCallError:
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
