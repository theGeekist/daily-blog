import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from orchestrator_utils import ModelCallError, call_model

EVIDENCE_SYNTHESIS_STAGE = "evidence_synthesis"


class EvidenceBrief(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic_id: str
    claim_count: int
    top_claims: list[str]
    problem_pressures: list[str]
    proposed_solutions: list[str]
    evidence_type_counts: dict[str, int]
    stance_breakdown: dict[str, int]
    dominant_pattern: str
    outline_strategy: str


EVIDENCE_BRIEF_SCHEMA: dict[str, Any] = EvidenceBrief.model_json_schema()


def synthesize_evidence_brief(
    topic_id: str,
    topic_label: str,
    claims: list[dict[str, str]],
    validated_sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    fallback = _build_fallback_brief(
        topic_id=topic_id,
        claims=claims,
        validated_sources=validated_sources,
    )
    prompt = _build_synthesis_prompt(
        topic_id=topic_id,
        topic_label=topic_label,
        claims=claims,
        validated_sources=validated_sources,
        fallback_brief=fallback,
    )

    try:
        result = call_model(EVIDENCE_SYNTHESIS_STAGE, prompt, schema=EVIDENCE_BRIEF_SCHEMA)
        payload = result.get("content", {})
        if isinstance(payload, dict):
            merged = dict(fallback)
            merged.update(payload)
            merged["topic_id"] = topic_id
            return _finalize_brief(merged), str(result.get("model_used", EVIDENCE_SYNTHESIS_STAGE))
    except ModelCallError:
        pass

    return fallback, "deterministic-synthesis"


def _build_fallback_brief(
    topic_id: str,
    claims: list[dict[str, str]],
    validated_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    priority = {"data": 0, "link": 1, "anecdote": 2}
    sorted_claims = sorted(
        claims,
        key=lambda c: (
            priority.get(str(c.get("evidence_type", "")).strip().lower(), 99),
            str(c.get("headline", "")).strip().lower(),
        ),
    )

    evidence_type_counts: dict[str, int] = {}
    problem_pressures = _unique_nonempty([c.get("problem_pressure", "") for c in claims], limit=8)
    proposed_solutions = _unique_nonempty([c.get("proposed_solution", "") for c in claims], limit=8)

    for claim in claims:
        evidence_type = str(claim.get("evidence_type", "")).strip().lower() or "unknown"
        evidence_type_counts[evidence_type] = evidence_type_counts.get(evidence_type, 0) + 1

    stance_breakdown: dict[str, int] = {}
    for src in validated_sources:
        stance = str(src.get("stance", "neutral")).strip().lower() or "neutral"
        stance_breakdown[stance] = stance_breakdown.get(stance, 0) + 1

    dominant_pattern = _infer_pattern(
        claim_count=len(claims),
        source_count=len(validated_sources),
        evidence_type_counts=evidence_type_counts,
        stance_breakdown=stance_breakdown,
    )
    outline_strategy = _infer_strategy(dominant_pattern)

    return {
        "topic_id": topic_id,
        "claim_count": len(claims),
        "top_claims": [
            str(c.get("headline", "")).strip() for c in sorted_claims[:5] if c.get("headline")
        ],
        "problem_pressures": problem_pressures,
        "proposed_solutions": proposed_solutions,
        "evidence_type_counts": evidence_type_counts,
        "stance_breakdown": stance_breakdown,
        "dominant_pattern": dominant_pattern,
        "outline_strategy": outline_strategy,
    }


def _finalize_brief(candidate: dict[str, Any]) -> dict[str, Any]:
    brief = EvidenceBrief.model_validate(candidate)
    dominant_pattern = _infer_pattern(
        claim_count=max(brief.claim_count, 0),
        source_count=sum(int(v) for v in brief.stance_breakdown.values()),
        evidence_type_counts=brief.evidence_type_counts,
        stance_breakdown=brief.stance_breakdown,
    )
    finalized = brief.model_dump()
    finalized["dominant_pattern"] = dominant_pattern
    finalized["outline_strategy"] = _infer_strategy(dominant_pattern)
    return finalized


def _build_synthesis_prompt(
    topic_id: str,
    topic_label: str,
    claims: list[dict[str, str]],
    validated_sources: list[dict[str, Any]],
    fallback_brief: dict[str, Any],
) -> str:
    claim_lines = []
    for claim in claims[:30]:
        claim_lines.append(
            "- "
            + " | ".join(
                [
                    f"headline={claim.get('headline', '')}",
                    f"pressure={claim.get('problem_pressure', '')}",
                    f"solution={claim.get('proposed_solution', '')}",
                    f"evidence_type={claim.get('evidence_type', '')}",
                ]
            )
        )

    source_lines = []
    for src in validated_sources[:20]:
        source_domain = str(src.get("domain", ""))
        source_stance = str(src.get("stance", "neutral"))
        source_cred = str(src.get("credibility_guess", ""))
        source_url = str(src.get("url", ""))
        source_lines.append(
            f"- domain={source_domain} | stance={source_stance} | "
            f"cred={source_cred} | {source_url}"
        )

    if not claim_lines:
        claim_lines = ["- no claims"]
    if not source_lines:
        source_lines = ["- no validated sources"]

    return "\n".join(
        [
            "Synthesize topic evidence into a concise structured brief for editorial planning.",
            "Return JSON only matching schema.",
            "",
            f"topic_id: {topic_id}",
            f"topic_label: {topic_label}",
            "",
            "claims:",
            *claim_lines,
            "",
            "validated_sources:",
            *source_lines,
            "",
            "baseline_inference:",
            json.dumps(fallback_brief, ensure_ascii=True),
        ]
    )


def _unique_nonempty(values: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _infer_pattern(
    claim_count: int,
    source_count: int,
    evidence_type_counts: dict[str, int],
    stance_breakdown: dict[str, int],
) -> str:
    if claim_count > 0:
        data_ratio = int(evidence_type_counts.get("data", 0)) / claim_count
        anecdote_ratio = int(evidence_type_counts.get("anecdote", 0)) / claim_count
        if data_ratio > 0.5:
            return "data-backed"
        if anecdote_ratio > 0.7:
            return "anecdotal"

    if source_count > 0:
        contradict_ratio = int(stance_breakdown.get("contradicts", 0)) / source_count
        if contradict_ratio > 0.2:
            return "contested"

    return "consensus"


def _infer_strategy(dominant_pattern: str) -> str:
    if dominant_pattern == "data-backed":
        return "implementation-guide"
    if dominant_pattern == "contested":
        return "analysis"
    if dominant_pattern == "anecdotal":
        return "caution"
    return "explainer"
