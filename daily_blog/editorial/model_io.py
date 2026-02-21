import json
import re
from pathlib import Path
from typing import Any

from orchestrator_utils import ModelCallError

EDITORIAL_STAGE = "editorial"

EDITORIAL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "title_options",
        "outline_markdown",
        "narrative_draft_markdown",
        "talking_points",
        "verification_checklist",
        "angle",
        "audience",
    ],
    "properties": {
        "title_options": {
            "type": "array",
            "items": {"type": "string"},
        },
        "outline_markdown": {"type": "string"},
        "narrative_draft_markdown": {"type": "string"},
        "talking_points": {
            "type": "array",
            "items": {"type": "string"},
        },
        "verification_checklist": {
            "type": "array",
            "items": {"type": "string"},
        },
        "angle": {"type": "string"},
        "audience": {"type": "string"},
    },
}


def load_model_route(path: Path) -> str:
    if not path.exists():
        return "codex-5.3"
    obj = json.loads(path.read_text(encoding="utf-8"))
    return str(obj.get(EDITORIAL_STAGE, {}).get("primary", "codex-5.3"))


def load_rules(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    obj = json.loads(path.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else {}


def has_min_outline_sections(outline_markdown: str, minimum: int = 3) -> bool:
    headings: set[str] = set()
    for line in outline_markdown.splitlines():
        match = re.match(r"^###?\s+(.+?)\s*$", line.strip())
        if match:
            headings.add(match.group(1).lower())
    return len(headings) >= minimum


def build_editorial_prompt(
    topic_label: str,
    why_it_matters: str,
    time_horizon: str,
    validated_sources: list[dict[str, Any]],
) -> str:
    source_lines = [
        f"- {src['domain']} | {src['credibility_guess']} | {src['url']}"
        for src in validated_sources
    ]
    if not source_lines:
        source_lines = ["- no validated sources available"]

    return "\n".join(
        [
            (
                "Generate a high-quality editorial package including title options, "
                "a detailed outline, key talking points, and a verification checklist."
            ),
            "",
            "Return JSON only. No prose outside JSON.",
            "",
            "Topic context:",
            f"- label: {topic_label}",
            f"- why_it_matters: {why_it_matters}",
            f"- time_horizon: {time_horizon}",
            "- validated_sources:",
            *source_lines,
            "",
            "Required JSON shape:",
            "{",
            '  "title_options": ["...", "...", "..."],',
            '  "outline_markdown": "...",',
            '  "narrative_draft_markdown": "...",',
            '  "talking_points": ["..."],',
            '  "verification_checklist": ["..."],',
            '  "angle": "...",',
            '  "audience": "..."',
            "}",
            "",
            "Quality requirements:",
            "- At least 3 non-redundant title options.",
            (
                "- outline_markdown must include at least 3 distinct markdown "
                "sections using H2 or H3 headings."
            ),
            (
                "- narrative_draft_markdown must include H2 sections for Intro hook, "
                "Storyline, Sections, and Outro."
            ),
            "- talking_points should be specific and execution oriented.",
            (
                "- verification_checklist should focus on factual correctness and "
                "source-backed claims."
            ),
        ]
    )


def validate_editorial_package(package: dict[str, Any]) -> None:
    for key in ("title_options", "talking_points", "verification_checklist"):
        values = package.get(key)
        if not isinstance(values, list) or not values:
            raise ModelCallError(f"editorial package missing non-empty list for '{key}'")
        if not all(isinstance(item, str) and item.strip() for item in values):
            raise ModelCallError(f"editorial package has invalid entries for '{key}'")

    outline = package.get("outline_markdown", "")
    if not isinstance(outline, str) or not outline.strip():
        raise ModelCallError("editorial package missing non-empty outline_markdown")
    if not has_min_outline_sections(outline, minimum=3):
        raise ModelCallError(
            "editorial package failed quality gate: outline needs >= 3 distinct H2/H3 sections"
        )

    narrative = package.get("narrative_draft_markdown", "")
    if not isinstance(narrative, str) or not narrative.strip():
        raise ModelCallError("editorial package missing non-empty narrative_draft_markdown")
    lower = narrative.lower()
    required_markers = ["## intro", "## storyline", "## sections", "## outro"]
    missing_markers = [marker for marker in required_markers if marker not in lower]
    if missing_markers:
        raise ModelCallError(
            "editorial package failed narrative gate: missing sections "
            + ", ".join(missing_markers)
        )

    for key in ("angle", "audience"):
        value = package.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ModelCallError(f"editorial package missing non-empty '{key}'")
