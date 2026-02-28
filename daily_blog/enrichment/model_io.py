import json
import logging
from typing import Any

from daily_blog.core.env_parsing import env_bool
from daily_blog.enrichment.helpers import credibility_for_domain, domain_for_url, normalize_url
from orchestrator_utils import ModelCallError, call_model

ENRICHMENT_STAGE = "enrichment"

logger = logging.getLogger(__name__)

SOURCE_ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["sources"],
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["url", "domain", "stance", "credibility_guess"],
                "properties": {
                    "url": {"type": "string"},
                    "domain": {"type": "string"},
                    "stance": {
                        "type": "string",
                        "enum": ["supports", "contradicts", "mixed", "neutral"],
                    },
                    "credibility_guess": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
            },
        }
    },
}

def build_enrichment_prompt(
    topic_label: str, keywords: list[str], known_sources: list[str], query_terms: list[str]
) -> str:
    return (
        "You are a research enrichment assistant with search/browser tools available.\n\n"
        "Task:\n"
        "- Research this topic using search/browser tools.\n"
        "- Find at least 3-5 high-quality supporting or corroborating sources.\n"
        "- Prefer primary sources, reputable technical docs, and credible reporting.\n"
        "- Return ONLY JSON matching the required schema. No prose, no markdown.\n\n"
        "Topic label:\n"
        f"{topic_label}\n\n"
        "Keywords:\n"
        f"{json.dumps(keywords, ensure_ascii=True)}\n\n"
        "Suggested query terms:\n"
        f"{json.dumps(query_terms, ensure_ascii=True)}\n\n"
        "Current known sources from existing claims (avoid duplicates unless needed):\n"
        f"{json.dumps(known_sources, ensure_ascii=True, indent=2)}\n\n"
        "Output JSON shape:\n"
        '{"sources":[{"url":"https://...","domain":"example.com","stance":"supports|contradicts|mixed|neutral","credibility_guess":"low|medium|high"}]}'
    )


def fetch_model_sources(
    topic_id: str,
    topic_label: str,
    keywords: list[str],
    known_sources: list[str],
    query_terms: list[str],
) -> tuple[list[dict[str, str]], str]:
    if env_bool("ENRICH_SKIP_MODEL", False):
        return [], "model-skipped"
    prompt = build_enrichment_prompt(
        topic_label=topic_label,
        keywords=keywords,
        known_sources=known_sources,
        query_terms=query_terms,
    )
    try:
        result = call_model(
            stage_name=ENRICHMENT_STAGE, prompt=prompt, schema=SOURCE_ENRICHMENT_SCHEMA
        )
    except ModelCallError as exc:
        logger.warning("Enrichment model call failed for topic_id=%s: %s", topic_id, exc)
        return [], "model-failed"

    payload = result.get("content", {})
    if not isinstance(payload, dict):
        logger.warning("Skipping enrichment for topic_id=%s due to non-object payload", topic_id)
        return [], "model-invalid"

    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list):
        logger.warning("Skipping enrichment for topic_id=%s due to missing sources array", topic_id)
        return [], "model-invalid"

    validated: list[dict[str, str]] = []
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        url = normalize_url(str(item.get("url", "")))
        if not url:
            continue
        domain = domain_for_url(url)
        stance = str(item.get("stance", "neutral")).strip().lower()
        if stance not in {"supports", "contradicts", "mixed", "neutral"}:
            stance = "neutral"
        credibility = str(item.get("credibility_guess", "")).strip().lower()
        if credibility not in {"low", "medium", "high"}:
            credibility = credibility_for_domain(domain)
        validated.append(
            {
                "url": url,
                "domain": domain,
                "stance": stance,
                "credibility_guess": credibility,
            }
        )

    model_name = str(result.get("model_used", "")).strip() or ENRICHMENT_STAGE
    return validated, f"{ENRICHMENT_STAGE}:{model_name}"


def build_discussion_signals_prompt(
    topic_label: str,
    query_terms: list[str],
    receipts: list[dict[str, object]],
) -> str:
    compact_receipts = [
        {
            "platform": str(item.get("platform", "")),
            "source_url": str(item.get("source_url", "")),
            "query_used": str(item.get("query_used", "")),
            "comment_count": item.get("comment_count", 0),
            "receipt_text": str(item.get("receipt_text", ""))[:4000],
        }
        for item in receipts
    ]
    return (
        "You are extracting grounded research signals from discussion receipts.\n\n"
        "Rules:\n"
        "- Use ONLY the provided receipts. Do not invent facts.\n"
        "- Capture problems people report and solution attempts people suggest.\n"
        "- Return ONLY JSON matching the schema.\n\n"
        "Topic:\n"
        f"{topic_label}\n\n"
        "Current query terms:\n"
        f"{json.dumps(query_terms, ensure_ascii=True)}\n\n"
        "Discussion receipts (query + comments actually fetched):\n"
        f"{json.dumps(compact_receipts, ensure_ascii=True)}\n\n"
        "Output schema:\n"
        '{"problem_statements":["..."],"solution_statements":["..."],"query_terms":["..."]}'
    )


def fetch_discussion_signals(
    *,
    topic_id: str,
    topic_label: str,
    query_terms: list[str],
    receipts: list[dict[str, object]],
) -> tuple[dict[str, list[str]], str]:
    empty = {"problem_statements": [], "solution_statements": [], "query_terms": []}
    if not receipts:
        return empty, "no-receipts"
    if env_bool("ENRICH_SKIP_MODEL", False):
        return empty, "model-skipped"

    prompt = build_discussion_signals_prompt(
        topic_label=topic_label,
        query_terms=query_terms,
        receipts=receipts,
    )
    try:
        # OpenCode CLI providers can occasionally emit list-wrapped JSON;
        # keep schema validation in-process for resilience.
        result = call_model(
            stage_name=ENRICHMENT_STAGE,
            prompt=prompt,
            schema=None,
        )
    except ModelCallError as exc:
        logger.warning("Discussion signal extraction failed for topic_id=%s: %s", topic_id, exc)
        return empty, "model-failed"

    payload = result.get("content", {})
    if isinstance(payload, list):
        object_candidates = [item for item in payload if isinstance(item, dict)]
        payload = object_candidates[0] if object_candidates else {}
    if not isinstance(payload, dict):
        return empty, "model-invalid"

    def _clean_list(name: str, limit: int) -> list[str]:
        raw = payload.get(name)
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            cleaned = " ".join(item.strip().split())
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            out.append(cleaned[:280])
            if len(out) >= limit:
                break
        return out

    signals = {
        "problem_statements": _clean_list("problem_statements", 8),
        "solution_statements": _clean_list("solution_statements", 8),
        "query_terms": _clean_list("query_terms", 20),
    }
    model_name = str(result.get("model_used", "")).strip() or ENRICHMENT_STAGE
    return signals, f"discussion-signals:{model_name}"
