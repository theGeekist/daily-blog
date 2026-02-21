# API Reference

This document describes the core APIs for integrating with the daily-blog pipeline.

## Core Module: `orchestrator_utils.py`

The `orchestrator_utils` module provides the primary interface for LLM integration, model routing, and schema validation.

### `call_model(stage_name, prompt, schema=None)`

Invokes LLM models with automatic fallback and JSON schema validation.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `stage_name` | `str` | Yes | Pipeline stage identifier (must exist in `model-routing.json`) |
| `prompt` | `str` | Yes | The prompt to send to the model |
| `schema` | `dict \| None` | No | JSON schema for response validation |

**Returns:**

```python
{
    "content": dict,    # Parsed JSON response from the model
    "model_used": str   # Which model actually responded (primary or fallback)
}
```

**Raises:**

| Exception | When |
|-----------|-------|
| `ModelCallError` | Stage name not found in model routing |
| `ModelCallError` | No usable primary/fallback model configured |
| `ModelCallError` | All models (primary + fallback) fail |
| `ModelCallError` | Schema validation fails |
| `ModelCallError` | CLI tool not found or times out |

**Example:**

```python
from orchestrator_utils import call_model

# Basic usage without schema
result = call_model(
    stage_name="topic_lifter",
    prompt="Cluster these claims into topics: ..."
)
print(result["model_used"])  # e.g., "ollama:qwen2.5:14b"

# With schema validation
result = call_model(
    stage_name="extractor",
    prompt="Extract claims from: ...",
    schema={
        "type": "object",
        "required": ["claims"],
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["claim", "confidence"]
                }
            }
        }
    }
)
```

---

## Model Resolution

Models are resolved from `config/model-routing.json` using the following logic:

1. **Load Configuration:** Read model routing for the given `stage_name`
2. **Apply Prompt Overrides:** Apply templates from `config/prompts.json` if present
3. **Try Primary:** Attempt to invoke the primary model
4. **Fallback on Failure:** If primary fails, try the fallback model
5. **Raise on All Fail:** If both models fail, raise `ModelCallError` with details

### Model Resolution Order

```
stage_name → model-routing.json → primary model
                                   ↓ (fails)
                               fallback model
                                   ↓ (fails)
                               ModelCallError
```

---

## Model Format Specification

Models are specified using a `tool:model` format. The following formats are supported:

### Supported Model Formats

| Format | CLI Tool | Example |
|--------|----------|---------|
| `codex-X.Y` | codex | `codex-5.3` |
| `gemini-X-pro` | gemini | `gemini-3-pro` |
| `ollama:model-name` | ollama | `ollama:qwen2.5:7b` |
| `ollama/model-name` | ollama | `ollama/qwen2.5:14b` |
| `model-name` (default) | opencode | `glm5` |

### Model Resolution Examples

```python
# In model-routing.json
{
    "topic_lifter": {
        "primary": "ollama:qwen2.5:14b",    # Uses ollama CLI
        "fallback": "gemini-3-pro"            # Uses gemini CLI
    },
    "ranker": {
        "primary": "deterministic-code",      # Uses opencode CLI
        "fallback": "deterministic-code"
    }
}
```

---

## Exception Types

### `ModelCallError`

Base exception for all model invocation failures.

**Attributes inherited from RuntimeError:**

- `message` (str): Human-readable error description

**Common Error Messages:**

| Error | Cause | Solution |
|-------|-------|----------|
| `Stage 'X' not found` | Missing config entry | Add stage to `model-routing.json` |
| `CLI tool not found: Y` | CLI not installed | Install the CLI tool (`ollama`, `codex`, etc.) |
| `CLI returned non-zero status` | Model execution failed | Check model availability, try different model |
| `No valid JSON found` | LLM returned non-JSON | Use model with structured output, add prompt template |
| `Schema validation failed at $.path` | Response doesn't match schema | Fix schema or update prompt |
| `CLI call timed out after 120s` | Model took too long | Increase timeout or use faster model |

---

## Prompt Override System

The `config/prompts.json` file allows modifying prompts at runtime without changing code.

### Prompt Template Format

```json
{
  "stage_name": {
    "template": "System instruction here.\n\n{prompt}",
    "prefix": "Additional context before prompt",
    "suffix": "Additional instruction after prompt"
  }
}
```

### Template Resolution Order

1. If `template` exists and contains `{prompt}`, replace `{prompt}` with the original prompt
2. Otherwise, use original prompt as-is
3. Prepend `prefix` if defined
4. Append `suffix` if defined

### Example

```json
{
  "extractor": {
    "template": "You are a claim extraction expert. Always return valid JSON.\n\n{prompt}",
    "prefix": "CONTEXT: You are analyzing RSS feeds for daily blog content.",
    "suffix": "REMEMBER: Return only valid JSON, no markdown."
  }
}
```

Resulting prompt sent to model:
```
CONTEXT: You are analyzing RSS feeds for daily blog content.

You are a claim extraction expert. Always return valid JSON.

[original prompt content here]

REMEMBER: Return only valid JSON, no markdown.
```

---

## Schema Validation

The module includes a lightweight JSON schema validator for validating LLM responses.

### Supported Schema Types

| Type | Description | Example |
|------|-------------|---------|
| `object` | Dictionary/object | `{"type": "object"}` |
| `array` | List/array | `{"type": "array"}` |
| `string` | Text string | `{"type": "string"}` |
| `number` | Float or integer | `{"type": "number"}` |
| `integer` | Whole number | `{"type": "integer"}` |
| `boolean` | True/false | `{"type": "boolean"}` |
| `null` | Null value | `{"type": "null"}` |
| `enum` | Specific values | `{"enum": ["a", "b", "c"]}` |

### Schema Keywords

| Keyword | Type | Description |
|---------|------|-------------|
| `type` | string | Expected data type |
| `required` | array[string] | Required keys for objects |
| `properties` | object | Property schemas for objects |
| `items` | object | Schema for array items |
| `enum` | array | Allowed values |

### Schema Validation Example

```python
schema = {
    "type": "object",
    "required": ["topics", "metadata"],
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "claims"],
                "properties": {
                    "name": {"type": "string"},
                    "claims": {"type": "array"}
                }
            }
        },
        "metadata": {
            "type": "object",
            "required": ["count"],
            "properties": {
                "count": {"type": "integer"},
                "source": {"type": "string", "enum": ["rss", "manual"]}
            }
        }
    }
}

result = call_model("topic_lifter", prompt="...", schema=schema)
# Raises ModelCallError if response doesn't match schema
```

---

## JSON Extraction

The module automatically extracts JSON from LLM outputs, handling:

1. **Fenced code blocks:** Markdown JSON blocks (` ```json ... ``` `)
2. **Embedded JSON:** First valid JSON object/array found in output
3. **Error on no JSON:** Raises `ModelCallError` if no valid JSON found

### Extraction Examples

```
Input: "Here's the result:\n```json\n{\"key\": \"value\"}\n```"
Output: {"key": "value"}

Input: "The answer is {\"result\": true} and that's it."
Output: {"result": true}

Input: "No JSON here, just text."
Output: ModelCallError raised
```

---

## Constants

```python
DEFAULT_MODEL_ROUTING_PATH = Path("config/model-routing.json")
DEFAULT_PROMPTS_PATH = Path("config/prompts.json")
DEFAULT_TIMEOUT_SECONDS = 120
```

These can be modified if using custom configuration paths.

---

## Logging

The module uses Python's standard `logging` framework:

```python
import logging
logger = logging.getLogger(__name__)

# Logs model invocations
logger.info("Calling model via CLI", extra={"cli": "ollama", "model": "qwen2.5:7b"})

# Logs failures
logger.warning("Model invocation failed for stage '%s': %s", stage_name, error)
```

Enable debug logging to see all model interactions:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```
