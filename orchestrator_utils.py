#!/usr/bin/env python3
# Compatibility shim — do not add new code here.
# The actual implementation lives in daily_blog/model_inference/caller.py.
from daily_blog.model_inference.caller import (  # noqa: F401
    DEFAULT_MODEL_ROUTING_PATH,
    DEFAULT_PROMPTS_PATH,
    DEFAULT_SCHEMA_RETRIES,
    _candidate_models,
    _dispatch_gemini,
    _dispatch_gemini_cli,
    _dispatch_model,
    _dispatch_ollama,
    _dispatch_openclaw,
    _dispatch_opencode,
    _extract_json_payload,
    _invoke_with_retries,
    _sanitize_gemini_schema,
    call_model,
)
from daily_blog.model_inference.errors import ModelCallError, ModelOutputValidationError  # noqa: F401
