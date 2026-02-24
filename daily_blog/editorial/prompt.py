import json
import re
from pathlib import Path
from typing import Any

from daily_blog.model_inference.config import load_model_routing
from daily_blog.model_inference.errors import ModelCallError

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
    try:
        routing = load_model_routing(path)
    except ModelCallError:
        return "codex-5.3"
    return str(routing.get(EDITORIAL_STAGE, {}).get("primary", "codex-5.3"))


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
    evidence_brief: dict[str, Any] | None = None,
    claims: list[dict[str, str]] | None = None,
) -> str:
    source_lines = [
        f"- {src['domain']} | {src['credibility_guess']} | {src['url']}"
        for src in validated_sources
    ]
    if not source_lines:
        source_lines = ["- no validated sources available"]
    claims = claims or []
    claim_lines = [
        (
            f"- {c.get('headline', '')} | pressure={c.get('problem_pressure', '')} "
            f"| solution={c.get('proposed_solution', '')} | evidence={c.get('evidence_type', '')}"
        )
        for c in claims[:12]
    ]
    if not claim_lines:
        claim_lines = ["- no mapped claims available"]
    evidence_brief = evidence_brief or {}
    strategy = str(evidence_brief.get("outline_strategy", "explainer")).strip().lower()
    strategy_requirements = {
        "analysis": (
            "- Include a 'Competing Views' section that references contradicting evidence and "
            "resolves the disagreement."
        ),
        "implementation-guide": (
            "- Include a 'Step-by-Step' section with concrete actions anchored to top claims."
        ),
        "caution": (
            "- Lead with caveats, uncertainty, and evidence gaps before prescribing actions."
        ),
        "explainer": (
            "- Emphasize conceptual clarity, plain-language framing, and balanced context."
        ),
    }
    strategy_requirement = strategy_requirements.get(strategy, strategy_requirements["explainer"])

    return "\n".join(
        [
            (
                "Generate a high-quality editorial package including title options, "
                "a detailed outline, key talking points, and a verification checklist."
            ),
            "",
            "Return JSON only. No prose outside JSON.",
            "Return a single JSON object. Do not wrap the result in an array.",
            "",
            "Topic context:",
            f"- label: {topic_label}",
            f"- why_it_matters: {why_it_matters}",
            f"- time_horizon: {time_horizon}",
            "- validated_sources:",
            *source_lines,
            "- mapped_claims:",
            *claim_lines,
            "- evidence_brief:",
            json.dumps(evidence_brief, ensure_ascii=True),
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
            "- Adapt the outline structure to the evidence brief's strategy and pattern.",
            strategy_requirement,
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
