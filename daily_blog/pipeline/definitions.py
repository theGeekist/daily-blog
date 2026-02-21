from dataclasses import dataclass


@dataclass(frozen=True)
class StageDefinition:
    name: str
    command: list[str]
    route_key: str
    default_model: str


DEFAULT_STAGES: tuple[StageDefinition, ...] = (
    StageDefinition("ingest", ["python3", "ingest_rss.py"], "ranker", "deterministic-code"),
    StageDefinition("score", ["python3", "score_rss.py"], "ranker", "deterministic-code"),
    StageDefinition(
        "extract_claims", ["python3", "extract_claims.py"], "extractor", "gemini-3-pro"
    ),
    StageDefinition("lift_topics", ["python3", "lift_topics.py"], "topic_lifter", "gemini-3-pro"),
    StageDefinition(
        "normalize_topics",
        ["python3", "normalize_topics.py"],
        "topic_curator",
        "ollama:qwen2.5",
    ),
    StageDefinition("enrich_topics", ["python3", "enrich_topics.py"], "enrichment", "codex-5.3"),
    StageDefinition(
        "generate_editorial",
        ["python3", "generate_editorial.py"],
        "editorial",
        "codex-5.3",
    ),
)


def configured_stages(skip_stages: set[str]) -> list[StageDefinition]:
    if not skip_stages:
        return list(DEFAULT_STAGES)
    return [stage for stage in DEFAULT_STAGES if stage.name not in skip_stages]
