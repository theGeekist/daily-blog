#!/usr/bin/env python3
import argparse
import hashlib
import importlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_settings_utils = importlib.import_module("daily_blog.insights.settings_utils")
coerce_field_value = _settings_utils.coerce_field_value
get_path_value = _settings_utils.get_path_value
set_path_value = _settings_utils.set_path_value

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "daily-blog.db"
DEFAULT_RULES_ENGINE = ROOT / "config" / "rules-engine.json"
DEFAULT_MODEL_ROUTING = ROOT / "config" / "model-routing.json"
DEFAULT_PROMPTS = ROOT / "config" / "prompts.json"
DEFAULT_PIPELINE_TIMEOUTS = ROOT / "config" / "pipeline-timeouts.json"
_REDDIT_CACHE: dict[str, dict] = {}
_RUN_LOCK = threading.Lock()
_RUN_PROC: subprocess.Popen | None = None
_RUN_LOG = ROOT / "data" / "insights_run.log"
_STAGES = [
    "ingest",
    "score",
    "extract_claims",
    "lift_topics",
    "normalize_topics",
    "enrich_topics",
    "generate_editorial",
]


def dict_rows(cursor: sqlite3.Cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_db(sqlite_path: Path, query: str, params: tuple = ()) -> list[dict]:
    if not sqlite_path.exists():
        return []
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(query, params)
        return dict_rows(cur)
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _snapshot_hash(value: dict) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _env_values() -> dict[str, str]:
    tracked_keys = [
        "PIPELINE_RETRIES",
        "PIPELINE_STAGE_TIMEOUT_SECONDS",
        "PIPELINE_STAGE_TIMEOUTS",
        "EXTRACT_MAX_MENTIONS",
        "ENRICH_FETCH_TIMEOUT_SECONDS",
        "ENRICH_FETCH_RETRIES",
        "ENRICH_DISCOVER_LIMIT",
        "ENRICH_MAX_KNOWN_CLAIM_URLS",
        "ENRICH_MAX_TOPICS",
        "ENRICH_SKIP_MODEL",
        "TOPIC_CURATOR_BATCH_SIZE",
        "FORCE_TOPIC_RECURATE",
        "EDITORIAL_STATIC_ONLY",
    ]
    return {k: os.getenv(k, "") for k in tracked_keys if k in os.environ}


def _effective_config() -> dict:
    stage_timeouts = _load_json_file(
        Path(os.getenv("PIPELINE_TIMEOUTS_PATH", str(DEFAULT_PIPELINE_TIMEOUTS)))
    )
    return {
        "schema_version": "prometheus-v2",
        "pipeline": {
            "retries": int(os.getenv("PIPELINE_RETRIES", "2") or 2),
            "stage_timeouts": stage_timeouts,
        },
        "rules_engine": _load_json_file(
            Path(os.getenv("RULES_ENGINE_CONFIG", str(DEFAULT_RULES_ENGINE)))
        ),
        "model_routing": _load_json_file(
            Path(os.getenv("MODEL_ROUTING_CONFIG", str(DEFAULT_MODEL_ROUTING)))
        ),
        "prompts": _load_json_file(Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS)))),
        "runtime": {
            "env": _env_values(),
        },
    }


def _prompt_usage_payload() -> dict:
    prompts = _load_json_file(Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS))))
    stage_map = {
        "extractor": {
            "script": "extract_claims.py",
            "purpose": "Extracts granular claims from raw mentions.",
            "inputs": ["mention_title", "mention_summary"],
            "outputs": ["claims"],
        },
        "topic_lifter": {
            "script": "lift_topics.py",
            "purpose": "Clusters claims into high-level topic slugs.",
            "inputs": ["claims"],
            "outputs": ["topic_slugs"],
        },
        "topic_curator": {
            "script": "normalize_topics.py",
            "purpose": "Normalizes topic labels and provides narrative context.",
            "inputs": ["topic_slug", "claims"],
            "outputs": ["normalized_label", "why_it_matters"],
        },
        "enrichment": {
            "script": "enrich_topics.py",
            "purpose": "Finds additional sources for a topic.",
            "inputs": ["topic_label", "claims"],
            "outputs": ["search_queries", "suggested_sources"],
        },
        "editorial": {
            "script": "generate_editorial.py",
            "purpose": "Drafts titles and outlines for the final blog post.",
            "inputs": ["topic_label", "claims", "enriched_sources"],
            "outputs": ["title_options", "outline_markdown"],
        },
    }
    stages: list[dict] = []
    for stage_name, spec in stage_map.items():
        stage_cfg = prompts.get(stage_name)
        active = isinstance(stage_cfg, dict) and any(
            isinstance(stage_cfg.get(key), str) and stage_cfg.get(key, "").strip()
            for key in ("prefix", "suffix", "template")
        )
        stages.append(
            {
                "stage": stage_name,
                "script": spec["script"],
                "purpose": spec["purpose"],
                "inputs": spec["inputs"],
                "outputs": spec["outputs"],
                "override_active": active,
                "supported_keys": ["prefix", "suffix", "template"],
            }
        )
    return {
        "config_path": str(Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS)))),
        "configured_stages": len([s for s in stages if s["override_active"]]),
        "stages": stages,
        "is_empty_object": prompts == {},
    }


def _prompt_stage_specs() -> dict[str, dict]:
    return {
        "extractor": {
            "script": "extract_claims.py",
            "purpose": "Extract one practical claim package from mention title/summary.",
            "default_template": "\n".join(
                [
                    "You are an extraction engine for content claims.",
                    "",
                    "Task:",
                    "- Read the mention metadata.",
                    "- Extract one practical claim and supporting fields.",
                    "- Return ONLY valid JSON (no prose, no markdown).",
                    "",
                    "Required output JSON fields:",
                    "- headline (string)",
                    "- who_cares (string)",
                    "- problem_pressure (string)",
                    "- proposed_solution (string)",
                    "- evidence_type (string enum: data|link|anecdote)",
                    "- sources (array of source URL strings)",
                    "",
                    "Mention title:",
                    "{mention_title}",
                    "",
                    "Mention summary:",
                    "{mention_summary}",
                ]
            ),
            "variables": [
                {
                    "name": "mention_title",
                    "type": "string",
                    "description": "Original mention title from RSS/source item.",
                },
                {
                    "name": "mention_summary",
                    "type": "string",
                    "description": (
                        "Mention summary/description text, stripped of HTML where possible."
                    ),
                },
            ],
            "inputs_example": {
                "mention_title": "How teams reduce LLM hallucinations in production",
                "mention_summary": (
                    "A practical writeup on retrieval checks, "
                    "schema validation, and fallback routing."
                ),
            },
            "output_contract": {
                "required": [
                    "headline",
                    "who_cares",
                    "problem_pressure",
                    "proposed_solution",
                    "evidence_type",
                    "sources",
                ],
                "evidence_type_enum": ["data", "link", "anecdote"],
            },
            "output_example": {
                "headline": (
                    "Teams are adding schema-validated extraction to reduce noisy summaries"
                ),
                "who_cares": "Content and platform engineers",
                "problem_pressure": (
                    "Unstructured feeds produce inconsistent claims and editorial drift"
                ),
                "proposed_solution": "Use strict JSON extraction with fallback heuristics",
                "evidence_type": "data",
                "sources": ["https://example.com/source"],
            },
            "notes": [
                "Fallback heuristics run when model output fails schema validation.",
                "At least one source URL is normalized with a fallback to mention URL.",
            ],
        },
        "topic_lifter": {
            "script": "lift_topics.py",
            "purpose": "Assign each claim to exactly one allowed topic slug.",
            "default_template": "\n".join(
                [
                    "You are a topic clustering engine for product and engineering claims.",
                    "",
                    "Task:",
                    "- Assign every claim to exactly one topic slug from the allowed list.",
                    "- Use only the provided claim_id values and only allowed topic_slug values.",
                    "- Return ONLY valid JSON matching the required schema.",
                    "",
                    "Allowed topic slugs:",
                    "{allowed_topic_slugs_json}",
                    "",
                    "Claims:",
                    "{claims_json}",
                    "",
                    'Output JSON shape: {"assignments":[{"claim_id":"...","topic_slug":"..."}]}',
                ]
            ),
            "variables": [
                {
                    "name": "allowed_topic_slugs_json",
                    "type": "json-array",
                    "description": "All permitted topic slugs including misc.",
                },
                {
                    "name": "claims_json",
                    "type": "json-array",
                    "description": "Claim list containing claim_id/headline/problem context.",
                },
            ],
            "inputs_example": {
                "allowed_topic_slugs_json": [
                    "ai",
                    "engineering",
                    "web",
                    "business",
                    "language",
                    "misc",
                ],
                "claims_json": [
                    {
                        "claim_id": "abc123",
                        "headline": "Schema-first extraction reduced parsing failures",
                        "problem_pressure": "Manual triage overhead is high",
                    }
                ],
            },
            "output_contract": {
                "required": ["assignments"],
                "item_required": ["claim_id", "topic_slug"],
                "constraints": [
                    "All input claim_id values must be assigned exactly once",
                    "topic_slug must be one of allowed topic slugs",
                ],
            },
            "output_example": {
                "assignments": [
                    {"claim_id": "abc123", "topic_slug": "engineering"},
                ]
            },
            "notes": [
                "Batch fallback uses keyword detection if model fails.",
            ],
        },
        "topic_curator": {
            "script": "normalize_topics.py",
            "purpose": (
                "Normalize topic labels/slugs for dashboard readability and stable taxonomy."
            ),
            "default_template": "\n".join(
                [
                    "You are a topic normalization and curation engine.",
                    "",
                    "Task:",
                    (
                        "- Preserve the same number of topics and keep "
                        "the original topic_id unchanged."
                    ),
                    "- Produce clean, human-readable display labels for dashboard use.",
                    ("- Keep normalized_topic_slug short and stable (lowercase kebab-case)."),
                    "- Return only valid JSON matching schema.",
                    "",
                    "Input topics:",
                    "{topics_json}",
                    "",
                    (
                        'Output shape: {"topics":[{"topic_id":"...",'
                        '"normalized_topic_slug":"...","normalized_topic_label":"...",'
                        '"curation_notes":"..."}]}'
                    ),
                ]
            ),
            "variables": [
                {
                    "name": "topics_json",
                    "type": "json-array",
                    "description": (
                        "Current topic rows including parent slug/label and claim context."
                    ),
                }
            ],
            "inputs_example": {
                "topics_json": [
                    {
                        "topic_id": "ai",
                        "parent_topic_slug": "ai",
                        "parent_topic_label": "Ai",
                        "claim_count": 6,
                    }
                ]
            },
            "output_contract": {
                "required": ["topics"],
                "item_required": [
                    "topic_id",
                    "normalized_topic_slug",
                    "normalized_topic_label",
                    "curation_notes",
                ],
                "constraints": [
                    "topic_id must match input topic IDs",
                    "normalized_topic_slug should be lowercase kebab-case",
                ],
            },
            "output_example": {
                "topics": [
                    {
                        "topic_id": "ai",
                        "normalized_topic_slug": "ai",
                        "normalized_topic_label": "AI",
                        "curation_notes": "Merged casing variants for consistency",
                    }
                ]
            },
            "notes": [
                "Fallback curator normalizes with deterministic slugify rules.",
            ],
        },
        "enrichment": {
            "script": "enrich_topics.py",
            "purpose": "Research additional topic sources and annotate stance/credibility.",
            "default_template": "\n".join(
                [
                    "You are a research enrichment assistant with search/browser tools available.",
                    "",
                    "Task:",
                    "- Research this topic using search/browser tools.",
                    "- Find at least 3-5 high-quality supporting or corroborating sources.",
                    "- Return ONLY JSON matching the required schema.",
                    "",
                    "Topic label:",
                    "{topic_label}",
                    "",
                    "Keywords:",
                    "{keywords_json}",
                    "",
                    "Suggested query terms:",
                    "{query_terms_json}",
                    "",
                    "Current known sources:\n{known_sources_json}",
                ]
            ),
            "variables": [
                {"name": "topic_label", "type": "string", "description": "Curated topic label."},
                {
                    "name": "keywords_json",
                    "type": "json-array",
                    "description": "Topic keywords list.",
                },
                {
                    "name": "query_terms_json",
                    "type": "json-array",
                    "description": "Search terms derived from topic and keywords.",
                },
                {
                    "name": "known_sources_json",
                    "type": "json-array",
                    "description": "Known claim-linked sources used for dedupe context.",
                },
            ],
            "inputs_example": {
                "topic_label": "AI deployment reliability",
                "keywords_json": ["llm", "validation", "fallback"],
                "query_terms_json": ["ai", "deployment", "reliability"],
                "known_sources_json": ["https://example.com/known"],
            },
            "output_contract": {
                "required": ["sources"],
                "item_required": ["url", "domain", "stance", "credibility_guess"],
                "stance_enum": ["supports", "contradicts", "mixed", "neutral"],
                "credibility_enum": ["low", "medium", "high"],
            },
            "output_example": {
                "sources": [
                    {
                        "url": "https://example.com/evidence",
                        "domain": "example.com",
                        "stance": "supports",
                        "credibility_guess": "high",
                    }
                ]
            },
            "notes": [
                "Pipeline still verifies fetchability and prunes low-credibility results.",
            ],
        },
        "editorial": {
            "script": "generate_editorial.py",
            "purpose": (
                "Generate title options, outline, narrative draft, and verification checklist."
            ),
            "default_template": "\n".join(
                [
                    (
                        "Generate a high-quality editorial package including title options, "
                        "a detailed outline, key talking points, and a verification checklist."
                    ),
                    "",
                    "Return JSON only. No prose outside JSON.",
                    "",
                    "Topic context:",
                    "- label: {topic_label}",
                    "- why_it_matters: {why_it_matters}",
                    "- time_horizon: {time_horizon}",
                    "- validated_sources:",
                    "{validated_sources_lines}",
                    "",
                    "Required JSON shape:",
                    '{"title_options":["..."],"outline_markdown":"...","narrative_draft_markdown":"...","talking_points":["..."],"verification_checklist":["..."],"angle":"...","audience":"..."}',
                ]
            ),
            "variables": [
                {"name": "topic_label", "type": "string", "description": "Topic display label."},
                {
                    "name": "why_it_matters",
                    "type": "string",
                    "description": "Topic importance statement from clustering stage.",
                },
                {
                    "name": "time_horizon",
                    "type": "string",
                    "description": "Topic timing category (flash/seasonal/evergreen).",
                },
                {
                    "name": "validated_sources_lines",
                    "type": "string",
                    "description": "Fetched/validated source list rendered as bullet lines.",
                },
            ],
            "inputs_example": {
                "topic_label": "AI deployment reliability",
                "why_it_matters": "Reliability shifts can invalidate production workflows quickly.",
                "time_horizon": "seasonal",
                "validated_sources_lines": "- docs.example.org | high | https://docs.example.org/post",
            },
            "output_contract": {
                "required": [
                    "title_options",
                    "outline_markdown",
                    "narrative_draft_markdown",
                    "talking_points",
                    "verification_checklist",
                    "angle",
                    "audience",
                ],
                "quality_gates": [
                    "outline_markdown must include at least 3 H2/H3 sections",
                    "narrative_draft_markdown must include Intro, Storyline, Sections, Outro",
                ],
            },
            "output_example": {
                "title_options": ["AI reliability shifts: what changed and what to do"],
                "outline_markdown": "## Hook\n## Thesis\n## Sections\n",
                "narrative_draft_markdown": "## Intro hook\n## Storyline\n## Sections\n## Outro",
                "talking_points": ["Signal map", "Decision framework"],
                "verification_checklist": ["Claims cited"],
                "angle": "Execution guide",
                "audience": "Editors and operators",
            },
            "notes": [
                "Evidence gate may suppress editorial output when status is BLOCK.",
            ],
        },
    }


def _resolve_prompt_spec(stage_id: str, spec: dict, overrides: dict) -> dict:
    default_template = str(spec.get("default_template") or "")
    stage_override = overrides.get(stage_id)
    override: dict[str, str] = {"prefix": "", "suffix": "", "template": ""}
    if isinstance(stage_override, dict):
        for key in ("prefix", "suffix", "template"):
            value = stage_override.get(key)
            override[key] = str(value) if isinstance(value, str) else ""

    template = override.get("template", "")
    prefix = override.get("prefix", "")
    suffix = override.get("suffix", "")
    warnings: list[str] = []
    if template.strip():
        if "{prompt}" in template:
            effective = template.replace("{prompt}", default_template)
        else:
            effective = default_template
            warnings.append(
                (
                    "template override is set but missing {prompt}; "
                    "default prompt is used with prefix/suffix only"
                )
            )
    else:
        effective = default_template
    if prefix.strip():
        effective = f"{prefix.strip()}\n\n{effective}"
    if suffix.strip():
        effective = f"{effective}\n\n{suffix.strip()}"

    missing_vars = []
    for variable in spec.get("variables", []):
        if not isinstance(variable, dict):
            continue
        name = str(variable.get("name") or "").strip()
        if not name:
            continue
        if "{" + name + "}" not in effective:
            missing_vars.append(name)
    if missing_vars:
        warnings.append(
            "effective template does not include placeholder markers for variables: "
            + ", ".join(missing_vars)
        )

    return {
        "stage_id": stage_id,
        "script": str(spec.get("script") or ""),
        "purpose": str(spec.get("purpose") or ""),
        "default_template": default_template,
        "effective_template": effective,
        "override": override,
        "variables": spec.get("variables", []),
        "inputs_example": spec.get("inputs_example", {}),
        "output_contract": spec.get("output_contract", {}),
        "output_example": spec.get("output_example", {}),
        "notes": spec.get("notes", []),
        "warnings": warnings,
        "contract_version": "prometheus-v1",
    }


def _prompt_specs_payload() -> dict:
    overrides = _load_json_file(Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS))))
    specs = _prompt_stage_specs()
    prompt_specs = [
        _resolve_prompt_spec(stage_id, spec, overrides) for stage_id, spec in specs.items()
    ]
    return {
        "contract_version": "prometheus-v1",
        "config_path": str(Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS)))),
        "prompt_specs": prompt_specs,
    }


def _settings_schema() -> dict:
    def rel(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    return {
        "schema_version": "prometheus-v2",
        "editable_sections": {
            "rules_engine": {
                "description": "Scoring, topic, and evidence thresholds.",
                "path": rel(Path(os.getenv("RULES_ENGINE_CONFIG", str(DEFAULT_RULES_ENGINE)))),
            },
            "model_routing": {
                "description": "Primary/fallback model routes per stage.",
                "path": rel(Path(os.getenv("MODEL_ROUTING_CONFIG", str(DEFAULT_MODEL_ROUTING)))),
            },
            "prompts": {
                "description": "Optional prompt templates per stage.",
                "path": rel(Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS)))),
            },
            "pipeline": {
                "description": "Retries and stage timeouts.",
                "fields": {
                    "retries": {
                        "type": "integer",
                        "min": 0,
                        "max": 10,
                        "help": "Retry attempts per stage.",
                    },
                    "stage_timeouts": {"type": "object", "help": "Per-stage timeout seconds."},
                },
            },
        },
    }


def _settings_form_definition() -> dict:
    return {
        "schema_version": "prometheus-v2",
        "groups": [
            {
                "id": "scoring",
                "title": "Scoring and Candidate Rules",
                "description": "Controls candidate selection thresholds and ranking components.",
                "fields": [
                    {
                        "path": "rules_engine.hard_rules.min_title_length",
                        "label": "Minimum Title Length",
                        "type": "integer",
                        "min": 5,
                        "max": 180,
                        "help": "Reject short/noisy titles below this length.",
                    },
                    {
                        "path": "rules_engine.hard_rules.max_candidates",
                        "label": "Max Candidates",
                        "type": "integer",
                        "min": 1,
                        "max": 100,
                        "help": "Maximum candidates emitted per run.",
                    },
                    {
                        "path": "rules_engine.hard_rules.max_per_topic",
                        "label": "Max Per Topic",
                        "type": "integer",
                        "min": 1,
                        "max": 20,
                        "help": "Caps topic concentration in the decision queue.",
                    },
                    {
                        "path": "rules_engine.hard_rules.min_final_score",
                        "label": "Minimum Final Score",
                        "type": "number",
                        "min": 0,
                        "max": 1,
                        "step": 0.01,
                        "help": "Drop candidates below this score.",
                    },
                    {
                        "path": "pipeline.retries",
                        "label": "Pipeline Retries",
                        "type": "integer",
                        "min": 0,
                        "max": 10,
                        "help": "Retry attempts per stage before fail.",
                    },
                ],
            },
            {
                "id": "evidence",
                "title": "Evidence Gate",
                "description": "Controls pass/warn/block gates for editorial readiness.",
                "fields": [
                    {
                        "path": "rules_engine.evidence_thresholds.min_sources",
                        "label": "Min Sources",
                        "type": "integer",
                        "min": 1,
                        "max": 50,
                        "help": "Minimum source count required before passing evidence gate.",
                    },
                    {
                        "path": "rules_engine.evidence_thresholds.min_fetched_ratio",
                        "label": "Min Fetched Ratio",
                        "type": "number",
                        "min": 0,
                        "max": 1,
                        "step": 0.01,
                        "help": "Minimum fetched_ok ratio required for PASS eligibility.",
                    },
                    {
                        "path": "rules_engine.evidence_thresholds.min_avg_credibility_score",
                        "label": "Min Avg Credibility",
                        "type": "number",
                        "min": 1,
                        "max": 3,
                        "step": 0.1,
                        "help": "Average credibility threshold (low=1, medium=2, high=3).",
                    },
                    {
                        "path": "rules_engine.evidence_thresholds.warn_min_fetched_ratio",
                        "label": "Warn Min Fetched Ratio",
                        "type": "number",
                        "min": 0,
                        "max": 1,
                        "step": 0.01,
                        "help": "Warn if below this fetched ratio.",
                    },
                    {
                        "path": "rules_engine.evidence_thresholds.warn_min_avg_credibility_score",
                        "label": "Warn Min Avg Credibility",
                        "type": "number",
                        "min": 1,
                        "max": 3,
                        "step": 0.1,
                        "help": "Warn if average credibility falls below this value.",
                    },
                    {
                        "path": "rules_engine.evidence_thresholds.min_domain_diversity",
                        "label": "Min Domain Diversity",
                        "type": "integer",
                        "min": 1,
                        "max": 20,
                        "help": "Distinct source domains required for stronger confidence.",
                    },
                    {
                        "path": (
                            "rules_engine.evidence_thresholds.block_anecdote_without_min_sources"
                        ),
                        "label": "Block Anecdote-Only Without Min Sources",
                        "type": "boolean",
                        "help": (
                            "If true, anecdotal-only topics remain blocked without enough sources."
                        ),
                    },
                    {
                        "path": "rules_engine.hard_rules.blocked_title_keywords",
                        "label": "Blocked Title Keywords",
                        "type": "list",
                        "item_type": "string",
                        "help": "Reject mention titles containing these keywords.",
                    },
                    {
                        "path": "rules_engine.actionability_keywords",
                        "label": "Actionability Keywords",
                        "type": "list",
                        "item_type": "string",
                        "help": "Keywords that increase actionability scoring.",
                    },
                    {
                        "path": "rules_engine.topics",
                        "label": "Topic Taxonomy (slug to keywords)",
                        "type": "map_list",
                        "help": "Map of topic slug to keyword list for fallback topic assignment.",
                    },
                ],
            },
            {
                "id": "runtime",
                "title": "Pipeline Runtime and Timeouts",
                "description": (
                    "Controls retries, extraction limits, and per-stage timeout budgets."
                ),
                "fields": [
                    {
                        "path": "runtime.env.EXTRACT_MAX_MENTIONS",
                        "label": "Extract Max Mentions",
                        "type": "integer",
                        "min": 10,
                        "max": 2000,
                        "help": "Upper bound for mentions processed by extraction stage.",
                    },
                    {
                        "path": "pipeline.stage_timeouts",
                        "label": "Stage Timeouts Map (seconds)",
                        "type": "map_integer",
                        "min": 30,
                        "max": 3600,
                        "help": (
                            "Per-stage timeout map (ingest, score, extract_claims, "
                            "lift_topics, normalize_topics, enrich_topics, generate_editorial)."
                        ),
                    },
                ],
            },
            {
                "id": "models",
                "title": "Model Routing",
                "description": (
                    "Primary/fallback models for each stage. Use local models where possible."
                ),
                "model_cards": [
                    {
                        "stage": "extractor",
                        "purpose": "Extract one reliable claim package per mention.",
                        "workload": "High-volume schema-constrained extraction.",
                        "reliability": "Strict JSON conformance and low hallucination.",
                        "guidance": "Use fast local instruction-following models first.",
                    },
                    {
                        "stage": "topic_lifter",
                        "purpose": "Assign each claim to exactly one valid topic slug.",
                        "workload": "Batch claim-to-topic mapping.",
                        "reliability": "No missing or duplicate assignments.",
                        "guidance": "Prefer models that stay consistent under enum constraints.",
                    },
                    {
                        "stage": "topic_curator",
                        "purpose": "Normalize topic slugs/labels for dashboard readability.",
                        "workload": "Small batch naming and cleanup.",
                        "reliability": "Stable slug naming across runs.",
                        "guidance": "Local small/medium model usually sufficient.",
                    },
                    {
                        "stage": "enrichment",
                        "purpose": "Find corroborating sources for each topic.",
                        "workload": "Search-heavy source proposal and validation.",
                        "reliability": "Factual quality and source diversity.",
                        "guidance": (
                            "Use strongest factual model available if local quality is weak."
                        ),
                    },
                    {
                        "stage": "editorial",
                        "purpose": "Generate titles, outline, narrative draft, and checklist.",
                        "workload": "Long-form structured writing.",
                        "reliability": "Must pass narrative section quality gates.",
                        "guidance": "Use creative long-context model with stable fallback.",
                    },
                ],
                "fields": [
                    {
                        "path": "model_routing.extractor.primary",
                        "label": "Extractor Primary",
                        "type": "string",
                        "help": (
                            "Model used for claim extraction. Optimized for detail retention."
                        ),
                    },
                    {
                        "path": "model_routing.extractor.fallback",
                        "label": "Extractor Fallback",
                        "type": "string",
                        "help": "Fallback when extractor primary fails.",
                    },
                    {
                        "path": "model_routing.extractor.local_candidates",
                        "label": "Extractor Local Candidates",
                        "type": "list",
                        "item_type": "string",
                        "help": "Candidate local models for extractor stage.",
                    },
                    {
                        "path": "model_routing.topic_lifter.primary",
                        "label": "Topic Lifter Primary",
                        "type": "string",
                        "help": (
                            "Model used to map claims to topics. Needs high semantic reasoning."
                        ),
                    },
                    {
                        "path": "model_routing.topic_lifter.fallback",
                        "label": "Topic Lifter Fallback",
                        "type": "string",
                        "help": "Fallback when topic-lifter primary fails.",
                    },
                    {
                        "path": "model_routing.topic_lifter.local_candidates",
                        "label": "Topic Lifter Local Candidates",
                        "type": "list",
                        "item_type": "string",
                        "help": "Candidate local models for topic lifter stage.",
                    },
                    {
                        "path": "model_routing.topic_curator.primary",
                        "label": "Topic Curator Primary",
                        "type": "string",
                        "help": (
                            "Model used for topic normalization and display labels. "
                            "Optimized for brevity."
                        ),
                    },
                    {
                        "path": "model_routing.topic_curator.fallback",
                        "label": "Topic Curator Fallback",
                        "type": "string",
                        "help": "Fallback for topic normalization stage.",
                    },
                    {
                        "path": "model_routing.topic_curator.local_candidates",
                        "label": "Topic Curator Local Candidates",
                        "type": "list",
                        "item_type": "string",
                        "help": "Candidate local models for topic curator stage.",
                    },
                    {
                        "path": "model_routing.editorial.primary",
                        "label": "Editorial Primary",
                        "type": "string",
                        "help": (
                            "Model used for title/outline narrative generation. "
                            "Creative writing focus."
                        ),
                    },
                    {
                        "path": "model_routing.editorial.fallback",
                        "label": "Editorial Fallback",
                        "type": "string",
                        "help": "Fallback model for editorial stage.",
                    },
                    {
                        "path": "model_routing.editorial.local_candidates",
                        "label": "Editorial Local Candidates",
                        "type": "list",
                        "item_type": "string",
                        "help": "Candidate local models for editorial stage.",
                    },
                    {
                        "path": "model_routing.enrichment.primary",
                        "label": "Enrichment Primary",
                        "type": "string",
                        "help": (
                            "Model used to suggest additional evidence sources. "
                            "High factual accuracy required."
                        ),
                    },
                    {
                        "path": "model_routing.enrichment.fallback",
                        "label": "Enrichment Fallback",
                        "type": "string",
                        "help": "Fallback for enrichment suggestions.",
                    },
                ],
            },
            {
                "id": "prompts",
                "title": "Prompt Templates",
                "description": (
                    "Per-stage prompt overrides with default and effective template visibility."
                ),
                "fields": [
                    {
                        "path": "prompts.extractor",
                        "label": "Extractor Prompt Override",
                        "type": "prompt_override",
                        "stage_id": "extractor",
                        "help": "Optional prefix/suffix/template overrides for extractor stage.",
                    },
                    {
                        "path": "prompts.topic_lifter",
                        "label": "Topic Lifter Prompt Override",
                        "type": "prompt_override",
                        "stage_id": "topic_lifter",
                        "help": "Optional prefix/suffix/template overrides for topic lifter stage.",
                    },
                    {
                        "path": "prompts.topic_curator",
                        "label": "Topic Curator Prompt Override",
                        "type": "prompt_override",
                        "stage_id": "topic_curator",
                        "help": (
                            "Optional prefix/suffix/template overrides for topic curator stage."
                        ),
                    },
                    {
                        "path": "prompts.enrichment",
                        "label": "Enrichment Prompt Override",
                        "type": "prompt_override",
                        "stage_id": "enrichment",
                        "help": "Optional prefix/suffix/template overrides for enrichment stage.",
                    },
                    {
                        "path": "prompts.editorial",
                        "label": "Editorial Prompt Override",
                        "type": "prompt_override",
                        "stage_id": "editorial",
                        "help": "Optional prefix/suffix/template overrides for editorial stage.",
                    },
                ],
            },
            {
                "id": "advanced",
                "title": "Advanced JSON Overrides",
                "description": "Raw JSON editors for power users. Normally not required.",
                "collapsible": True,
                "collapsed": True,
                "fields": [
                    {
                        "path": "rules_engine",
                        "label": "Rules Engine JSON",
                        "type": "object",
                        "help": "Full rules-engine object override.",
                    },
                    {
                        "path": "model_routing",
                        "label": "Model Routing JSON",
                        "type": "object",
                        "help": "Full model-routing object override.",
                    },
                    {
                        "path": "prompts",
                        "label": "Prompts JSON",
                        "type": "object",
                        "help": "Full prompts object override.",
                    },
                ],
            },
        ],
    }


def _settings_form_payload() -> dict:
    effective = _effective_config()
    form = _settings_form_definition()
    prompt_specs = _prompt_specs_payload()
    values: dict[str, object] = {}
    defaults: dict[str, object] = {}
    for group in form.get("groups", []):
        fields = group.get("fields", []) if isinstance(group, dict) else []
        for field in fields:
            if not isinstance(field, dict):
                continue
            path = str(field.get("path") or "")
            if not path:
                continue
            field_type = str(field.get("type") or "string")
            if field_type == "prompt_override":
                stage_id = str(field.get("stage_id") or "")
                spec = next(
                    (
                        s
                        for s in prompt_specs.get("prompt_specs", [])
                        if isinstance(s, dict) and str(s.get("stage_id") or "") == stage_id
                    ),
                    {},
                )
                values[path] = spec.get("override", {}) if isinstance(spec, dict) else {}
                defaults[path] = {"prefix": "", "suffix": "", "template": ""}
                continue
            values[path] = get_path_value(effective, path)
            defaults[path] = field.get("default")

    for path, value in values.items():
        if defaults.get(path) is not None:
            continue
        if isinstance(value, bool):
            defaults[path] = False
        elif isinstance(value, int):
            defaults[path] = 0
        elif isinstance(value, float):
            defaults[path] = 0.0
        elif isinstance(value, list):
            defaults[path] = []
        elif isinstance(value, dict):
            defaults[path] = {}
        else:
            defaults[path] = ""
    return {
        "form": form,
        "values": values,
        "defaults": defaults,
        "prompt_specs": prompt_specs.get("prompt_specs", []),
        "effective_hash": _snapshot_hash(effective),
    }


def _field_definitions() -> dict[str, dict]:
    form = _settings_form_definition()
    field_defs: dict[str, dict] = {}
    for group in form.get("groups", []):
        if not isinstance(group, dict):
            continue
        for field in group.get("fields", []):
            if isinstance(field, dict) and isinstance(field.get("path"), str):
                field_defs[field["path"]] = field
    return field_defs


def _build_field_diffs(fields_payload: dict) -> list[dict]:
    current_payload = _settings_form_payload()
    current_values = current_payload.get("values", {})
    diffs: list[dict] = []
    for path, next_value in fields_payload.items():
        before = current_values.get(path)
        if _canonical_json(before) == _canonical_json(next_value):
            continue
        diffs.append({"path": path, "before": before, "after": next_value})
    return diffs


def _validate_settings_fields(fields_payload: dict) -> tuple[bool, list[dict]]:
    field_defs = _field_definitions()

    errors: list[dict] = []
    for path, raw_value in fields_payload.items():
        definition = field_defs.get(path)
        if definition is None:
            errors.append({"path": path, "message": "unknown field"})
            continue

        field_type = str(definition.get("type") or "string")
        try:
            value = coerce_field_value(field_type, raw_value)
        except (ValueError, TypeError, json.JSONDecodeError):
            errors.append({"path": path, "message": f"invalid {field_type} value"})
            continue

        if field_type == "list" and isinstance(value, list):
            min_items = definition.get("min_items")
            if isinstance(min_items, int) and len(value) < min_items:
                errors.append({"path": path, "message": f"must include at least {min_items} items"})

        if field_type == "map_integer" and isinstance(value, dict):
            min_value = definition.get("min")
            max_value = definition.get("max")
            for key, entry_value in value.items():
                if isinstance(min_value, (int, float)) and entry_value < min_value:
                    errors.append({"path": f"{path}.{key}", "message": f"must be >= {min_value}"})
                if isinstance(max_value, (int, float)) and entry_value > max_value:
                    errors.append({"path": f"{path}.{key}", "message": f"must be <= {max_value}"})

        if field_type == "map_list" and isinstance(value, dict):
            if not value:
                errors.append({"path": path, "message": "must include at least one topic key"})
            for key, keywords in value.items():
                if not str(key).strip():
                    errors.append({"path": path, "message": "map keys cannot be empty"})
                if not isinstance(keywords, list):
                    errors.append(
                        {"path": f"{path}.{key}", "message": "must be a list of keywords"}
                    )
                elif not keywords:
                    errors.append(
                        {"path": f"{path}.{key}", "message": "keyword list cannot be empty"}
                    )

        if field_type == "prompt_override" and isinstance(value, dict):
            template = str(value.get("template") or "")
            if template.strip() and "{prompt}" not in template:
                errors.append(
                    {
                        "path": path,
                        "message": "template override must include {prompt} placeholder",
                    }
                )

        min_value = definition.get("min")
        max_value = definition.get("max")
        if isinstance(value, (int, float)):
            if isinstance(min_value, (int, float)) and value < min_value:
                errors.append({"path": path, "message": f"must be >= {min_value}"})
            if isinstance(max_value, (int, float)) and value > max_value:
                errors.append({"path": path, "message": f"must be <= {max_value}"})

    return len(errors) == 0, errors


def _validate_settings_patch(payload: object) -> tuple[bool, list[dict]]:
    errors: list[dict] = []
    if not isinstance(payload, dict):
        return False, [{"path": "$", "message": "payload must be an object"}]
    allowed_sections = {"rules_engine", "model_routing", "prompts", "pipeline"}
    for key in payload.keys():
        if key not in allowed_sections:
            errors.append({"path": key, "message": "unknown top-level section"})

    pipeline = payload.get("pipeline")
    if pipeline is not None:
        if not isinstance(pipeline, dict):
            errors.append({"path": "pipeline", "message": "pipeline must be object"})
        else:
            retries = pipeline.get("retries")
            if retries is not None and (
                not isinstance(retries, int) or retries < 0 or retries > 10
            ):
                errors.append(
                    {"path": "pipeline.retries", "message": "must be integer in range [0, 10]"}
                )
            stage_timeouts = pipeline.get("stage_timeouts")
            if stage_timeouts is not None:
                if not isinstance(stage_timeouts, dict):
                    errors.append(
                        {"path": "pipeline.stage_timeouts", "message": "must be an object"}
                    )
                else:
                    for stage, value in stage_timeouts.items():
                        if not isinstance(stage, str):
                            errors.append(
                                {
                                    "path": "pipeline.stage_timeouts",
                                    "message": "stage keys must be strings",
                                }
                            )
                        if not isinstance(value, int) or value <= 0:
                            errors.append(
                                {
                                    "path": f"pipeline.stage_timeouts.{stage}",
                                    "message": "must be positive integer",
                                }
                            )

    for section_key in ("rules_engine", "model_routing", "prompts"):
        section = payload.get(section_key)
        if section is not None and not isinstance(section, dict):
            errors.append({"path": section_key, "message": "must be object"})

    return len(errors) == 0, errors


def _write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _apply_settings_patch(payload: dict) -> dict:
    rules_path = Path(os.getenv("RULES_ENGINE_CONFIG", str(DEFAULT_RULES_ENGINE)))
    model_path = Path(os.getenv("MODEL_ROUTING_CONFIG", str(DEFAULT_MODEL_ROUTING)))
    prompts_path = Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS)))
    timeouts_path = Path(os.getenv("PIPELINE_TIMEOUTS_PATH", str(DEFAULT_PIPELINE_TIMEOUTS)))

    if "rules_engine" in payload:
        _write_json_file(rules_path, payload["rules_engine"])
    if "model_routing" in payload:
        _write_json_file(model_path, payload["model_routing"])
    if "prompts" in payload:
        _write_json_file(prompts_path, payload["prompts"])
    pipeline = payload.get("pipeline")
    if isinstance(pipeline, dict):
        if "stage_timeouts" in pipeline and isinstance(pipeline["stage_timeouts"], dict):
            _write_json_file(timeouts_path, pipeline["stage_timeouts"])
        if "retries" in pipeline:
            os.environ["PIPELINE_RETRIES"] = str(int(pipeline["retries"]))

    effective = _effective_config()
    return {
        "applied": True,
        "effective_config": effective,
        "effective_hash": _snapshot_hash(effective),
    }


def _update_env_file_value(key: str, value: str) -> None:
    env_path = ROOT / ".env"
    lines: list[str] = []
    found = False
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith(f"{key}="):
            updated.append(f"{key}={value}")
            found = True
        else:
            updated.append(raw_line)
    if not found:
        updated.append(f"{key}={value}")
    env_path.write_text("\n".join(updated).rstrip("\n") + "\n", encoding="utf-8")


def _apply_settings_fields(fields_payload: dict) -> dict:
    rules_path = Path(os.getenv("RULES_ENGINE_CONFIG", str(DEFAULT_RULES_ENGINE)))
    model_path = Path(os.getenv("MODEL_ROUTING_CONFIG", str(DEFAULT_MODEL_ROUTING)))
    prompts_path = Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS)))
    timeouts_path = Path(os.getenv("PIPELINE_TIMEOUTS_PATH", str(DEFAULT_PIPELINE_TIMEOUTS)))

    rules = _load_json_file(rules_path)
    model = _load_json_file(model_path)
    prompts = _load_json_file(prompts_path)
    timeouts = _load_json_file(timeouts_path)

    field_defs = _field_definitions()
    normalized_payload: dict[str, object] = {}
    for path, raw_value in fields_payload.items():
        definition = field_defs.get(path, {})
        field_type = str(definition.get("type") or "string")
        normalized_payload[path] = coerce_field_value(field_type, raw_value)

    diffs = _build_field_diffs(normalized_payload)

    for path, coerced in normalized_payload.items():
        if path == "rules_engine":
            if isinstance(coerced, dict):
                rules = coerced
            continue
        if path == "model_routing":
            if isinstance(coerced, dict):
                model = coerced
            continue
        if path.startswith("rules_engine."):
            inner = path[len("rules_engine.") :]
            set_path_value(rules, inner, coerced)
            continue
        if path.startswith("runtime.env."):
            env_key = path[len("runtime.env.") :]
            env_value = str(coerced)
            os.environ[env_key] = env_value
            _update_env_file_value(env_key, env_value)
            continue
        if path.startswith("model_routing."):
            inner = path[len("model_routing.") :]
            if isinstance(coerced, list):
                set_path_value(model, inner, coerced)
            else:
                set_path_value(model, inner, str(coerced or ""))
            continue
        if path == "prompts":
            coerced_prompts = coerce_field_value("object", coerced)
            prompts = coerced_prompts if isinstance(coerced_prompts, dict) else {}
            continue
        if path.startswith("prompts."):
            inner = path[len("prompts.") :]
            if isinstance(coerced, dict):
                stage = str(inner).split(".")[0]
                prompts[stage] = {
                    "prefix": str(coerced.get("prefix") or ""),
                    "suffix": str(coerced.get("suffix") or ""),
                    "template": str(coerced.get("template") or ""),
                }
            else:
                set_path_value(prompts, inner, str(coerced or ""))
            continue
        if path == "pipeline.retries":
            retries = int(str(coerced))
            os.environ["PIPELINE_RETRIES"] = str(retries)
            _update_env_file_value("PIPELINE_RETRIES", str(retries))
            continue
        if path == "pipeline.stage_timeouts" and isinstance(coerced, dict):
            for stage, timeout_value in coerced.items():
                timeouts[str(stage)] = int(timeout_value)
            continue
        if path.startswith("pipeline.stage_timeouts."):
            stage = path[len("pipeline.stage_timeouts.") :]
            if stage:
                timeouts[stage] = int(str(coerced))

    _write_json_file(rules_path, rules)
    _write_json_file(model_path, model)
    _write_json_file(prompts_path, prompts)
    _write_json_file(timeouts_path, timeouts)

    effective = _effective_config()
    return {
        "applied": True,
        "changed": diffs,
        "effective_config": effective,
        "effective_hash": _snapshot_hash(effective),
    }


def ensure_topic_curation_columns(sqlite_path: Path) -> None:
    if not sqlite_path.exists():
        return
    conn = sqlite3.connect(sqlite_path)
    try:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='topic_clusters'"
        ).fetchall()
        if not table_rows:
            return
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(topic_clusters)").fetchall()
            if len(row) > 1
        }
        if "normalized_topic_slug" not in columns:
            conn.execute(
                "ALTER TABLE topic_clusters ADD COLUMN "
                "normalized_topic_slug TEXT NOT NULL DEFAULT ''"
            )
        if "normalized_topic_label" not in columns:
            conn.execute(
                "ALTER TABLE topic_clusters ADD COLUMN "
                "normalized_topic_label TEXT NOT NULL DEFAULT ''"
            )
        if "curation_notes" not in columns:
            conn.execute(
                "ALTER TABLE topic_clusters ADD COLUMN curation_notes TEXT NOT NULL DEFAULT ''"
            )
        if "curator_model_route_used" not in columns:
            conn.execute(
                "ALTER TABLE topic_clusters ADD COLUMN "
                "curator_model_route_used TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def ensure_prometheus_tables(sqlite_path: Path) -> None:
    if not sqlite_path.exists():
        return
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_config_snapshots (
                run_id TEXT PRIMARY KEY,
                snapshot_hash TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_deltas (
                run_id TEXT PRIMARY KEY,
                base_run_id TEXT NOT NULL,
                config_diff_json TEXT NOT NULL,
                metrics_diff_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ui_metrics (
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def latest_snapshot_payload(sqlite_path: Path) -> dict:
    rows = query_db(
        sqlite_path,
        """
        SELECT run_id, snapshot_hash, snapshot_json, created_at
        FROM run_config_snapshots
        ORDER BY created_at DESC
        LIMIT 1
        """,
    )
    if not rows:
        return {}
    row = rows[0]
    payload = {}
    try:
        payload = json.loads(str(row.get("snapshot_json") or "{}"))
    except json.JSONDecodeError:
        payload = {}
    return {
        "run_id": row.get("run_id", ""),
        "snapshot_hash": row.get("snapshot_hash", ""),
        "snapshot": payload,
        "created_at": row.get("created_at", ""),
    }


def delta_payload(sqlite_path: Path, run_id: str) -> dict:
    if not run_id:
        run_id = latest_run_id(sqlite_path)
    if not run_id:
        return {}
    delta_rows = query_db(
        sqlite_path,
        """
        SELECT run_id, base_run_id, config_diff_json, metrics_diff_json, created_at
        FROM run_deltas
        WHERE run_id = ?
        LIMIT 1
        """,
        (run_id,),
    )
    if not delta_rows:
        return {
            "run_id": run_id,
            "base_run_id": "",
            "config_diff": {},
            "metrics_diff": {},
            "created_at": "",
        }
    row = delta_rows[0]
    try:
        config_diff = json.loads(str(row.get("config_diff_json") or "{}"))
    except json.JSONDecodeError:
        config_diff = {}
    try:
        metrics_diff = json.loads(str(row.get("metrics_diff_json") or "{}"))
    except json.JSONDecodeError:
        metrics_diff = {}
    return {
        "run_id": row.get("run_id", run_id),
        "base_run_id": row.get("base_run_id", ""),
        "config_diff": config_diff,
        "metrics_diff": metrics_diff,
        "created_at": row.get("created_at", ""),
    }


def write_ui_metric(sqlite_path: Path, run_id: str, event_type: str, payload: dict) -> None:
    if not sqlite_path.exists():
        return
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute(
            """
            INSERT INTO ui_metrics (run_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (run_id or "", event_type, _canonical_json(payload)),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def ui_metrics_payload(sqlite_path: Path, limit: int = 30) -> list[dict]:
    rows = query_db(
        sqlite_path,
        """
        SELECT metric_id, run_id, event_type, payload_json, created_at
        FROM ui_metrics
        ORDER BY metric_id DESC
        LIMIT ?
        """,
        (limit,),
    )
    out: list[dict] = []
    for row in rows:
        payload = {}
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            payload = {}
        out.append(
            {
                "metric_id": row.get("metric_id", 0),
                "run_id": row.get("run_id", ""),
                "event_type": row.get("event_type", ""),
                "payload": payload,
                "created_at": row.get("created_at", ""),
            }
        )
    return out


def latest_run_id(sqlite_path: Path) -> str:
    rows = query_db(sqlite_path, "SELECT MAX(run_id) AS run_id FROM candidate_scores")
    if not rows:
        return ""
    return str(rows[0].get("run_id") or "")


def run_id_to_iso(run_id: str) -> str:
    if not run_id or len(run_id) != 16 or run_id[8] != "T" or not run_id.endswith("Z"):
        return ""
    return (
        f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]}T{run_id[9:11]}:{run_id[11:13]}:{run_id[13:15]}Z"
    )


def summary_payload(sqlite_path: Path) -> dict:
    run_id = latest_run_id(sqlite_path)
    counts = {
        "mentions": 0,
        "claims": 0,
        "topics": 0,
        "candidates": 0,
        "sources": 0,
        "sources_fetched": 0,
    }
    count_queries = {
        "mentions": "SELECT COUNT(*) AS n FROM mentions",
        "claims": "SELECT COUNT(*) AS n FROM claims",
        "topics": "SELECT COUNT(*) AS n FROM topic_clusters",
        "sources": "SELECT COUNT(*) AS n FROM enrichment_sources",
        "sources_fetched": "SELECT COUNT(*) AS n FROM enrichment_sources WHERE fetched_ok = 1",
    }
    for key, sql in count_queries.items():
        rows = query_db(sqlite_path, sql)
        counts[key] = int(rows[0]["n"]) if rows else 0

    if run_id:
        rows = query_db(
            sqlite_path,
            "SELECT COUNT(*) AS n FROM candidate_scores WHERE run_id = ?",
            (run_id,),
        )
        counts["candidates"] = int(rows[0]["n"]) if rows else 0

    run_rows = []
    if run_id:
        run_rows = query_db(
            sqlite_path,
            """
            SELECT MIN(started_at) AS started_at,
                   MAX(finished_at) AS finished_at,
                   SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END) AS failed_stages
            FROM run_metrics
            WHERE run_id = ?
            """,
            (run_id,),
        )

    run_meta = run_rows[0] if run_rows else {}
    started_at = str(run_meta.get("started_at") or "")
    finished_at = str(run_meta.get("finished_at") or "")
    if not started_at:
        started_at = run_id_to_iso(run_id)
    if not finished_at:
        finished_at = started_at

    return {
        "latest_run_id": run_id,
        "latest_run_started_at": started_at,
        "latest_run_finished_at": finished_at,
        "latest_run_failed_stages": int(run_meta.get("failed_stages") or 0),
        **counts,
    }


def candidates_payload(sqlite_path: Path, run_id: str, limit: int) -> list[dict]:
    if not run_id:
        return []
    return query_db(
        sqlite_path,
        """
        SELECT c.rank_index, c.topic, c.final_score, c.novelty_status,
               c.novelty_score, c.recency_score, c.corroboration_score,
               c.source_diversity_score, c.actionability_score,
               m.title, m.url, m.source, c.entry_id
        FROM candidate_scores c
        LEFT JOIN mentions m ON m.entry_id = c.entry_id
        WHERE c.run_id = ?
        ORDER BY c.rank_index ASC
        LIMIT ?
        """,
        (run_id, limit),
    )


def topics_payload(sqlite_path: Path, run_id: str) -> list[dict]:
    if not run_id:
        return []
    return query_db(
        sqlite_path,
        """
        SELECT tc.topic_id,
               tc.parent_topic_slug AS topic_slug,
               COALESCE(
                   NULLIF(tc.normalized_topic_label, ''),
                   tc.parent_topic_label
               ) AS label,
               tc.why_it_matters,
               tc.time_horizon,
               tc.claim_count,
               ROUND(AVG(cs.final_score), 4) AS avg_score,
               SUM(CASE WHEN es.fetched_ok = 1 THEN 1 ELSE 0 END) AS fetched_sources,
               COUNT(es.url) AS total_sources
        FROM topic_clusters tc
        LEFT JOIN candidate_scores cs ON cs.topic = tc.parent_topic_slug AND cs.run_id = ?
        LEFT JOIN enrichment_sources es ON es.topic_id = tc.topic_id
        GROUP BY tc.topic_id, tc.parent_topic_slug, tc.parent_topic_label, tc.claim_count
        ORDER BY avg_score DESC
        """,
        (run_id,),
    )


def runs_payload(sqlite_path: Path, limit: int) -> list[dict]:
    return query_db(
        sqlite_path,
        """
        SELECT run_id, stage_name, status, duration_ms, model_route_used,
               actual_model_used, started_at, finished_at
        FROM run_metrics
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def sources_payload(sqlite_path: Path, limit: int) -> list[dict]:
    return query_db(
        sqlite_path,
        """
        SELECT es.topic_id,
               tc.parent_topic_slug AS topic_slug,
               COALESCE(
                   NULLIF(tc.normalized_topic_label, ''),
                   tc.parent_topic_label
               ) AS topic_label,
               es.domain,
               es.url,
               es.stance,
               es.credibility_guess,
               es.fetched_ok,
               es.created_at
        FROM enrichment_sources es
        LEFT JOIN topic_clusters tc ON tc.topic_id = es.topic_id
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


def sources_payload_filtered(
    sqlite_path: Path,
    limit: int,
    topic_id: str = "",
    topic_slug: str = "",
    fetched_only: bool = False,
) -> list[dict]:
    where: list[str] = []
    params: list = []
    if topic_id:
        where.append("es.topic_id = ?")
        params.append(topic_id)
    elif topic_slug:
        where.append("tc.parent_topic_slug = ?")
        params.append(topic_slug)
    if fetched_only:
        where.append("es.fetched_ok = 1")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)
    return query_db(
        sqlite_path,
        f"""
        SELECT es.topic_id,
               tc.parent_topic_slug AS topic_slug,
               COALESCE(
                   NULLIF(tc.normalized_topic_label, ''),
                   tc.parent_topic_label
               ) AS topic_label,
               es.domain,
               es.url,
               es.stance,
               es.credibility_guess,
               es.fetched_ok,
               es.created_at
        FROM enrichment_sources es
        LEFT JOIN topic_clusters tc ON tc.topic_id = es.topic_id
        {where_sql}
        ORDER BY es.created_at DESC
        LIMIT ?
        """,
        tuple(params),
    )


def candidate_detail_payload(sqlite_path: Path, run_id: str, entry_id: str) -> dict:
    if not run_id or not entry_id:
        return {}

    candidate_rows = query_db(
        sqlite_path,
        """
        SELECT c.run_id, c.rank_index, c.entry_id, c.topic,
               c.final_score, c.novelty_status,
               c.novelty_score, c.recency_score, c.corroboration_score,
               c.source_diversity_score, c.actionability_score,
               m.title, m.url, m.source, m.summary, m.published
        FROM candidate_scores c
        LEFT JOIN mentions m ON m.entry_id = c.entry_id
        WHERE c.run_id = ? AND c.entry_id = ?
        LIMIT 1
        """,
        (run_id, entry_id),
    )
    if not candidate_rows:
        return {}
    candidate = candidate_rows[0]

    claims = query_db(
        sqlite_path,
        """
        SELECT claim_id, headline, who_cares, problem_pressure, proposed_solution,
               evidence_type, sources_json, model_route_used
        FROM claims
        WHERE entry_id = ?
        """,
        (entry_id,),
    )

    topics = query_db(
        sqlite_path,
        """
        SELECT DISTINCT tc.topic_id,
               tc.parent_topic_slug AS parent_topic_slug,
               COALESCE(
                   NULLIF(tc.normalized_topic_label, ''),
                   tc.parent_topic_label
               ) AS parent_topic_label,
               tc.why_it_matters,
               tc.time_horizon
        FROM claims c
        JOIN claim_topic_map ctm ON ctm.claim_id = c.claim_id
        JOIN topic_clusters tc ON tc.topic_id = ctm.topic_id
        WHERE c.entry_id = ?
        """,
        (entry_id,),
    )

    if not topics and candidate.get("topic"):
        topics = query_db(
            sqlite_path,
            """
            SELECT topic_id,
                   parent_topic_slug AS parent_topic_slug,
                   COALESCE(
                       NULLIF(normalized_topic_label, ''),
                       parent_topic_label
                   ) AS parent_topic_label,
                   why_it_matters,
                   time_horizon
            FROM topic_clusters
            WHERE parent_topic_slug = ?
            """,
            (candidate.get("topic"),),
        )

    topic_ids = [t.get("topic_id") for t in topics if t.get("topic_id")]
    sources: list[dict] = []
    editorial: list[dict] = []
    if topic_ids:
        placeholders = ",".join("?" for _ in topic_ids)
        sources = query_db(
            sqlite_path,
            f"""
            SELECT es.topic_id,
                   tc.parent_topic_slug AS topic_slug,
                   COALESCE(
                       NULLIF(tc.normalized_topic_label, ''),
                       tc.parent_topic_label
                   ) AS topic_label,
                   es.domain,
                   es.url,
                   es.stance,
                   es.credibility_guess,
                   es.fetched_ok
            FROM enrichment_sources es
            LEFT JOIN topic_clusters tc ON tc.topic_id = es.topic_id
            WHERE es.topic_id IN ({placeholders})
            ORDER BY fetched_ok DESC, credibility_guess DESC
            LIMIT 50
            """,
            tuple(topic_ids),
        )
        editorial = query_db(
            sqlite_path,
            f"""
            SELECT topic_id, title_options_json, outline_markdown,
                   talking_points_json, narrative_draft_markdown,
                   verification_checklist_json, angle, audience,
                   evidence_status, evidence_reasons_json,
                   evidence_ui_state, evidence_brief_json, model_route_used
            FROM editorial_candidates
            WHERE topic_id IN ({placeholders})
            """,
            tuple(topic_ids),
        )

    social = reddit_post_metrics(entry_id)

    return {
        "candidate": candidate,
        "claims": claims,
        "topics": topics,
        "sources": sources,
        "editorial": editorial,
        "social": social,
    }


def reddit_post_metrics(entry_id: str) -> dict:
    if not entry_id.startswith("t3_"):
        return {}
    if entry_id in _REDDIT_CACHE:
        return _REDDIT_CACHE[entry_id]

    post_id = entry_id[3:]
    url = f"https://www.reddit.com/comments/{post_id}.json?limit=1"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "daily-blog-insights/0.1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        post = payload[0]["data"]["children"][0]["data"]
        metrics = {
            "score": int(post.get("score") or 0),
            "num_comments": int(post.get("num_comments") or 0),
            "upvote_ratio": float(post.get("upvote_ratio") or 0.0),
            "created_utc": float(post.get("created_utc") or 0.0),
        }
        _REDDIT_CACHE[entry_id] = metrics
        return metrics
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ):
        _REDDIT_CACHE[entry_id] = {}
        return {}


class InsightsHandler(SimpleHTTPRequestHandler):
    sqlite_path = DEFAULT_DB

    def _json(self, payload: dict | list, status: int = 200) -> None:
        envelope = {"schema_version": "prometheus-v2", "data": payload}
        body = json.dumps(envelope, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/run_start":
            payload = self._read_json_body()
            force = bool(payload.get("force"))
            ok, message = start_pipeline_run(force=force)
            status = run_status_payload(self.sqlite_path)
            status["message"] = message
            self._json(status, status=200 if ok else 409)
            return
        if parsed.path == "/api/settings/validate":
            payload = self._read_json_body()
            if isinstance(payload.get("fields"), dict):
                ok, errors = _validate_settings_fields(payload["fields"])
                changed = _build_field_diffs(payload["fields"])
                self._json(
                    {
                        "ok": ok,
                        "errors": errors,
                        "changed": changed,
                    },
                    status=200 if ok else 400,
                )
            else:
                ok, errors = _validate_settings_patch(payload)
                self._json({"ok": ok, "errors": errors}, status=200 if ok else 400)
            return
        if parsed.path == "/api/settings/apply":
            payload = self._read_json_body()
            if isinstance(payload.get("fields"), dict):
                ok, errors = _validate_settings_fields(payload["fields"])
            else:
                ok, errors = _validate_settings_patch(payload)
            if not ok:
                self._json({"ok": False, "errors": errors}, status=400)
                return
            if isinstance(payload.get("fields"), dict):
                applied = _apply_settings_fields(payload["fields"])
            else:
                applied = _apply_settings_patch(payload)
            self._json({"ok": True, **applied})
            return
        if parsed.path == "/api/ui_metrics":
            payload = self._read_json_body()
            run_id = str(payload.get("run_id") or "")
            event_type = str(payload.get("event_type") or "")
            metric_payload = payload.get("payload")
            if not event_type or not isinstance(metric_payload, dict):
                self._json(
                    {"ok": False, "error": "event_type and payload(object) required"},
                    status=400,
                )
                return
            write_ui_metric(
                self.sqlite_path, run_id=run_id, event_type=event_type, payload=metric_payload
            )
            self._json({"ok": True})
            return
        self.send_error(404, "Not found")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/summary":
            self._json(summary_payload(self.sqlite_path))
            return
        if parsed.path == "/api/candidates":
            qs = parse_qs(parsed.query)
            run_id = qs.get("run_id", [latest_run_id(self.sqlite_path)])[0]
            limit = int(qs.get("limit", ["25"])[0])
            self._json(candidates_payload(self.sqlite_path, run_id, limit))
            return
        if parsed.path == "/api/topics":
            qs = parse_qs(parsed.query)
            run_id = qs.get("run_id", [latest_run_id(self.sqlite_path)])[0]
            self._json(topics_payload(self.sqlite_path, run_id))
            return
        if parsed.path == "/api/runs":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["30"])[0])
            self._json(runs_payload(self.sqlite_path, limit))
            return
        if parsed.path == "/api/sources":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["40"])[0])
            topic_id = qs.get("topic_id", [""])[0]
            topic_slug = qs.get("topic_slug", [""])[0]
            fetched_only = qs.get("fetched_only", ["0"])[0] == "1"
            self._json(
                sources_payload_filtered(
                    self.sqlite_path,
                    limit=limit,
                    topic_id=topic_id,
                    topic_slug=topic_slug,
                    fetched_only=fetched_only,
                )
            )
            return
        if parsed.path == "/api/candidate_detail":
            qs = parse_qs(parsed.query)
            run_id = qs.get("run_id", [latest_run_id(self.sqlite_path)])[0]
            entry_id = qs.get("entry_id", [""])[0]
            self._json(candidate_detail_payload(self.sqlite_path, run_id, entry_id))
            return
        if parsed.path == "/api/run_status":
            self._json(run_status_payload(self.sqlite_path))
            return
        if parsed.path == "/api/settings/schema":
            self._json(_settings_schema())
            return
        if parsed.path == "/api/settings/form":
            self._json(_settings_form_payload())
            return
        if parsed.path == "/api/settings/prompt_specs":
            self._json(_prompt_specs_payload())
            return
        if parsed.path == "/api/settings/effective":
            effective = _effective_config()
            snapshot = latest_snapshot_payload(self.sqlite_path)
            self._json(
                {
                    "effective_config": effective,
                    "effective_hash": _snapshot_hash(effective),
                    "prompt_usage": _prompt_usage_payload(),
                    "prompt_specs": _prompt_specs_payload().get("prompt_specs", []),
                    "latest_snapshot": snapshot,
                }
            )
            return
        if parsed.path == "/api/delta":
            qs = parse_qs(parsed.query)
            run_id = qs.get("run_id", [latest_run_id(self.sqlite_path)])[0]
            self._json(delta_payload(self.sqlite_path, run_id))
            return
        if parsed.path == "/api/ui_metrics":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["30"])[0])
            self._json(ui_metrics_payload(self.sqlite_path, limit=limit))
            return
        return super().do_GET()


def start_pipeline_run(force: bool = False) -> tuple[bool, str]:
    global _RUN_PROC
    with _RUN_LOCK:
        if _RUN_PROC and _RUN_PROC.poll() is None and not force:
            return False, "Pipeline run already in progress"
        if _RUN_PROC and _RUN_PROC.poll() is None and force:
            _RUN_PROC.terminate()
        _RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        log_handle = _RUN_LOG.open("w", encoding="utf-8")
        _RUN_PROC = subprocess.Popen(
            ["python3", "run_pipeline.py"],
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    return True, "Pipeline run started"


def run_status_payload(sqlite_path: Path) -> dict:
    with _RUN_LOCK:
        proc = _RUN_PROC
    running = bool(proc and proc.poll() is None)
    return_code = proc.poll() if proc else None

    stages = [{"stage": stage, "status": "pending"} for stage in _STAGES]
    stage_index = {s["stage"]: i for i, s in enumerate(stages)}
    last_line = ""

    if _RUN_LOG.exists():
        lines = _RUN_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
        if lines:
            last_line = lines[-1]
        for line in lines:
            start_match = re.match(r"^\[([^\]]+)\]\s+Attempt\s+\d+/\d+\s+route=.*$", line.strip())
            if start_match:
                stage = start_match.group(1)
                if stage in stage_index and stages[stage_index[stage]]["status"] == "pending":
                    stages[stage_index[stage]]["status"] = "running"
                continue
            m = re.match(r"^\[([^\]]+)\]\s+(OK|FAIL)$", line.strip())
            if not m:
                continue
            stage = m.group(1)
            status = "ok" if m.group(2) == "OK" else "failed"
            if stage in stage_index:
                stages[stage_index[stage]]["status"] = status

    completed = sum(1 for s in stages if s["status"] in {"ok", "failed"})
    running_count = sum(1 for s in stages if s["status"] == "running")
    progress = int(((completed + (0.5 * running_count)) / len(stages)) * 100) if stages else 0

    summary = summary_payload(sqlite_path)
    return {
        "running": running,
        "return_code": return_code,
        "progress": progress,
        "stages": stages,
        "last_log_line": last_line,
        "latest_run_id": summary.get("latest_run_id", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local insights dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("INSIGHTS_VIEWER_PORT", "8877")))
    parser.add_argument("--db", default=str(os.getenv("SQLITE_PATH", str(DEFAULT_DB))))
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    os.chdir(ROOT)
    InsightsHandler.sqlite_path = Path(args.db)
    ensure_topic_curation_columns(InsightsHandler.sqlite_path)
    ensure_prometheus_tables(InsightsHandler.sqlite_path)
    server = ThreadingHTTPServer((args.host, args.port), InsightsHandler)
    url = f"http://{args.host}:{args.port}/docs/viewer/dashboard.html"
    print(f"Serving insights dashboard at {url}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        with _RUN_LOCK:
            if _RUN_PROC and _RUN_PROC.poll() is None:
                _RUN_PROC.terminate()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
