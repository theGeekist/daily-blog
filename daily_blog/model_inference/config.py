import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from daily_blog.model_inference.errors import ModelCallError


def load_model_routing(config_path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelCallError(f"Model routing file not found: {config_path}") from exc
    except JSONDecodeError as exc:
        raise ModelCallError(f"Invalid JSON in model routing file: {config_path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ModelCallError(f"Model routing file must contain an object: {config_path}")
    return loaded


def load_prompt_overrides(config_path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def apply_prompt_overrides(stage_name: str, prompt: str, prompts_path: Path) -> str:
    prompts = load_prompt_overrides(prompts_path)
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
