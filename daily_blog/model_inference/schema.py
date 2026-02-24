import json
import re
from json import JSONDecodeError
from json.decoder import JSONDecoder
from typing import Any

from daily_blog.model_inference.errors import ModelOutputValidationError


def sanitize_gemini_schema(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            if key in {"title", "examples", "default", "additionalProperties"}:
                continue
            cleaned[key] = sanitize_gemini_schema(child)
        return cleaned
    if isinstance(value, list):
        return [sanitize_gemini_schema(item) for item in value]
    return value


def extract_json_payload(text: str) -> Any:
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


def validate_schema(instance: Any, schema: dict[str, Any]) -> None:
    _validate_node(instance=instance, schema=schema, path="$")


def _unwrap_single_object_array(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return value


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
