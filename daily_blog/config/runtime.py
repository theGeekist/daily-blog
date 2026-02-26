from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from daily_blog.core.json_utils import load_json_file

ALL_ENV_KEYS: set[str] = {
    "DAILY_BOARD_PATH",
    "EDITORIAL_STATIC_ONLY",
    "ENRICH_DISCOVER_LIMIT",
    "ENRICH_DISCUSSION_MAX_COMMENTS",
    "ENRICH_DISCUSSION_MAX_THREADS",
    "ENRICH_DISCUSSION_TIMEOUT_SECONDS",
    "ENRICH_FETCH_BACKOFF_SECONDS",
    "ENRICH_FETCH_RETRIES",
    "ENRICH_FETCH_TIMEOUT_SECONDS",
    "ENRICH_FETCH_USER_AGENT",
    "ENRICH_MAX_KNOWN_CLAIM_URLS",
    "ENRICH_MAX_TOPICS",
    "ENRICH_SKIP_MODEL",
    "EXTRACT_MAX_MENTIONS",
    "FEEDS_FILE",
    "FORCE_TOPIC_RECURATE",
    "MAX_ITEMS_PER_FEED",
    "MODEL_ROUTING_CONFIG",
    "OUTPUT_JSONL",
    "PIPELINE_RETRIES",
    "PIPELINE_SKIP_STAGES",
    "PIPELINE_STAGE_TIMEOUTS",
    "PIPELINE_STAGE_TIMEOUT_SECONDS",
    "PIPELINE_TIMEOUTS_PATH",
    "PROMPTS_CONFIG",
    "RESEARCH_PACK_PATH",
    "RULES_ENGINE_CONFIG",
    "RUN_ID",
    "SQLITE_PATH",
    "TOPIC_CURATOR_BATCH_SIZE",
    "TOP_OUTLINES_PATH",
}


def _env_int(
    environ: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int = 0,
) -> int:
    raw = environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


def _env_bool(environ: Mapping[str, str], key: str, default: bool = False) -> bool:
    raw = (environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_csv_or_json_list(environ: Mapping[str, str], key: str) -> set[str]:
    raw = (environ.get(key) or "").strip()
    if not raw:
        return set()
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, list):
        return {str(v).strip() for v in loaded if str(v).strip()}
    return {part.strip() for part in raw.split(",") if part.strip()}


def _env_json_int_map(environ: Mapping[str, str], key: str) -> dict[str, int]:
    raw = (environ.get(key) or "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in loaded.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, int) and v > 0:
            out[k] = v
    return out


@dataclass(frozen=True)
class PathsConfig:
    sqlite_path: Path
    model_routing_config: Path
    rules_engine_config: Path
    prompts_config: Path
    pipeline_timeouts_path: Path
    top_outlines_path: Path
    research_pack_path: Path


@dataclass(frozen=True)
class PipelineConfig:
    retries: int
    skip_stages: set[str]
    stage_timeout_seconds: int
    stage_timeouts_override: dict[str, int]


@dataclass(frozen=True)
class EnrichmentConfig:
    fetch_timeout_seconds: int
    discover_limit: int
    max_known_claim_urls: int
    max_topics: int


@dataclass(frozen=True)
class EditorialConfig:
    static_only: bool


@dataclass(frozen=True)
class AppConfig:
    paths: PathsConfig
    pipeline: PipelineConfig
    enrichment: EnrichmentConfig
    editorial: EditorialConfig


def load_app_config(
    *,
    project_root: Path,
    environ: Mapping[str, str],
) -> AppConfig:
    paths = PathsConfig(
        sqlite_path=Path(environ.get("SQLITE_PATH", "./data/daily-blog.db")),
        model_routing_config=Path(
            environ.get("MODEL_ROUTING_CONFIG", str(project_root / "config" / "model-routing.json"))
        ),
        rules_engine_config=Path(
            environ.get("RULES_ENGINE_CONFIG", str(project_root / "config" / "rules-engine.json"))
        ),
        prompts_config=Path(
            environ.get("PROMPTS_CONFIG", str(project_root / "config" / "prompts.json"))
        ),
        pipeline_timeouts_path=Path(
            environ.get(
                "PIPELINE_TIMEOUTS_PATH", str(project_root / "config" / "pipeline-timeouts.json")
            )
        ),
        top_outlines_path=Path(environ.get("TOP_OUTLINES_PATH", "./data/top_outlines.md")),
        research_pack_path=Path(environ.get("RESEARCH_PACK_PATH", "./data/research_pack.json")),
    )
    pipeline = PipelineConfig(
        retries=_env_int(environ, "PIPELINE_RETRIES", 2, minimum=1),
        skip_stages=_env_csv_or_json_list(environ, "PIPELINE_SKIP_STAGES"),
        stage_timeout_seconds=_env_int(environ, "PIPELINE_STAGE_TIMEOUT_SECONDS", 300, minimum=1),
        stage_timeouts_override=_env_json_int_map(environ, "PIPELINE_STAGE_TIMEOUTS"),
    )
    enrichment = EnrichmentConfig(
        fetch_timeout_seconds=_env_int(environ, "ENRICH_FETCH_TIMEOUT_SECONDS", 10, minimum=1),
        discover_limit=_env_int(environ, "ENRICH_DISCOVER_LIMIT", 10, minimum=0),
        max_known_claim_urls=_env_int(environ, "ENRICH_MAX_KNOWN_CLAIM_URLS", 24, minimum=1),
        max_topics=_env_int(environ, "ENRICH_MAX_TOPICS", 0, minimum=0),
    )
    editorial = EditorialConfig(
        static_only=_env_bool(environ, "EDITORIAL_STATIC_ONLY", default=False),
    )
    return AppConfig(
        paths=paths,
        pipeline=pipeline,
        enrichment=enrichment,
        editorial=editorial,
    )


def resolve_stage_timeouts(stage_names: list[str], config: AppConfig) -> dict[str, int]:
    timeouts = {stage: config.pipeline.stage_timeout_seconds for stage in stage_names}
    config_timeouts = load_json_file(config.paths.pipeline_timeouts_path)
    for key, value in config_timeouts.items():
        if key in timeouts and isinstance(value, int) and value > 0:
            timeouts[key] = value
    for key, value in config.pipeline.stage_timeouts_override.items():
        if key in timeouts and value > 0:
            timeouts[key] = value
    return timeouts
