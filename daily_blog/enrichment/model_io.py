import json
import logging
import os
from typing import Any

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
    if os.getenv("ENRICH_SKIP_MODEL", "0") == "1":
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
            credibility = credibility_for_domain(domain, url)
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
