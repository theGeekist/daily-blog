#!/usr/bin/env python3
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from daily_blog.core.env import load_env_file
from daily_blog.core.env_parsing import env_bool, env_int
from daily_blog.core.progress import elapsed_ms, emit_progress
from daily_blog.core.time_utils import now_iso
from orchestrator_utils import ModelCallError, call_model

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
DEFAULT_CONFIG_PATH = "./config/rules-engine.json"
TOPIC_LIFTER_STAGE = "topic_lifter"
MAX_CLAIMS_PER_BATCH = 10

logger = logging.getLogger(__name__)


def read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def init_topic_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS topic_clusters (
            topic_id TEXT PRIMARY KEY,
            parent_topic_slug TEXT NOT NULL,
            parent_topic_label TEXT NOT NULL,
            normalized_topic_slug TEXT NOT NULL DEFAULT '',
            normalized_topic_label TEXT NOT NULL DEFAULT '',
            curation_notes TEXT NOT NULL DEFAULT '',
            curator_model_route_used TEXT NOT NULL DEFAULT '',
            why_it_matters TEXT NOT NULL,
            time_horizon TEXT NOT NULL,
            claim_count INTEGER NOT NULL,
            keywords_json TEXT NOT NULL,
            model_route_used TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS claim_topic_map (
            claim_id TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            model_route_used TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (claim_id, topic_id)
        )
        """
    )
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(claim_topic_map)").fetchall()
        if len(row) > 1
    }
    if "model_route_used" not in columns:
        conn.execute("ALTER TABLE claim_topic_map ADD COLUMN model_route_used TEXT")
    topic_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(topic_clusters)").fetchall()
        if len(row) > 1
    }
    if "normalized_topic_slug" not in topic_columns:
        conn.execute(
            "ALTER TABLE topic_clusters ADD COLUMN normalized_topic_slug TEXT NOT NULL DEFAULT ''"
        )
    if "normalized_topic_label" not in topic_columns:
        conn.execute(
            "ALTER TABLE topic_clusters ADD COLUMN normalized_topic_label TEXT NOT NULL DEFAULT ''"
        )
    if "curation_notes" not in topic_columns:
        conn.execute(
            "ALTER TABLE topic_clusters ADD COLUMN curation_notes TEXT NOT NULL DEFAULT ''"
        )
    if "curator_model_route_used" not in topic_columns:
        conn.execute(
            "ALTER TABLE topic_clusters ADD COLUMN "
            "curator_model_route_used TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()


def detect_topic(text: str, topics: dict[str, list[str]]) -> str:
    lower = text.lower()
    for slug, keywords in topics.items():
        for kw in keywords:
            if kw.lower() in lower:
                return slug
    return "misc"


def label_for_slug(slug: str) -> str:
    special = {
        "ai": "AI",
        "ml": "ML",
        "llm": "LLM",
        "web": "Web",
        "misc": "General Engineering",
    }
    if slug in special:
        return special[slug]
    return slug.replace("_", " ").title()


def why_it_matters_for_slug(slug: str) -> str:
    mapping = {
        "ai": "Model capability and reliability changes can alter engineering decisions quickly.",
        "engineering": "Software delivery quality and maintainability impact team velocity.",
        "web": "Web stack changes directly affect product UX and delivery costs.",
        "business": "Go-to-market and monetization shifts affect execution priorities.",
        "language": "Language trends influence communication quality and audience framing.",
    }
    return mapping.get(slug, "This topic appears repeatedly and may influence planning decisions.")


def time_horizon_for_count(count: int) -> str:
    if count >= 5:
        return "evergreen"
    if count >= 3:
        return "seasonal"
    return "flash"


def read_claims(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        """
        SELECT claim_id, headline, problem_pressure, proposed_solution
        FROM claims
        """
    ).fetchall()


def chunk_claims(claims: list[tuple], batch_size: int) -> list[list[tuple]]:
    if batch_size <= 0:
        return [claims]
    return [claims[idx : idx + batch_size] for idx in range(0, len(claims), batch_size)]


def effective_batch_size(default_size: int = MAX_CLAIMS_PER_BATCH) -> int:
    raw_override = os.getenv("TOPIC_LIFTER_BATCH_SIZE", "").strip()
    if raw_override:
        try:
            parsed = int(raw_override)
            return parsed if parsed > 0 else 1
        except ValueError:
            pass

    model_name = os.getenv("MODEL_NAME", "").strip().lower()
    # Local Ollama inference is resource-constrained; keep topic_lifter strictly
    # sequential with one claim per model call by default.
    if model_name.startswith("ollama/") or model_name.startswith("ollama:"):
        return 1
    return default_size


def batch_index(idx: int, total_batches: int) -> str:
    return f"{idx}/{total_batches}"


def build_assignment_schema(topic_slugs: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["assignments"],
        "properties": {
            "assignments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["claim_id", "topic_slug"],
                    "properties": {
                        "claim_id": {"type": "string"},
                        "topic_slug": {"type": "string", "enum": topic_slugs},
                    },
                },
            }
        },
    }


def build_topic_prompt(batch_claims: list[tuple], topic_slugs: list[str]) -> str:
    payload = [
        {
            "claim_id": claim_id,
            "headline": headline,
            "problem_pressure": problem,
        }
        for claim_id, headline, problem, _ in batch_claims
    ]
    claims_json = json.dumps(payload, ensure_ascii=True, indent=2)
    slugs_json = json.dumps(topic_slugs, ensure_ascii=True)
    return (
        "You are a topic clustering engine for product and engineering claims.\n\n"
        "Task:\n"
        "- Assign every claim to exactly one topic slug from the allowed list.\n"
        "- Use only the provided claim_id values and only allowed topic_slug values.\n"
        "- Assign a claim to 'misc' ONLY if it shares no domain, entities, or problem-type "
        "with any other claim in the batch. Avoid 'misc' whenever the claim plausibly fits "
        "another slug.\n"
        "- Return ONLY valid JSON matching the required schema.\n\n"
        "Allowed topic slugs:\n"
        f"{slugs_json}\n\n"
        "Claims:\n"
        f"{claims_json}\n\n"
        "Output JSON shape:\n"
        '{"assignments":[{"claim_id":"...","topic_slug":"..."}]}'
    )


def assign_topics_with_model(
    batch_claims: list[tuple], topics_cfg: dict[str, list[str]]
) -> tuple[dict[str, str], str]:
    allowed_slugs = sorted(set(topics_cfg.keys()) | {"misc"})
    claim_ids = [str(row[0]) for row in batch_claims]
    schema = build_assignment_schema(topic_slugs=allowed_slugs)
    prompt = build_topic_prompt(batch_claims=batch_claims, topic_slugs=allowed_slugs)

    model_result = call_model(stage_name=TOPIC_LIFTER_STAGE, prompt=prompt, schema=schema)
    payload = model_result.get("content", {})
    if not isinstance(payload, dict):
        raise ModelCallError("Topic-lifter output must be a JSON object")

    raw_assignments = payload.get("assignments")
    if not isinstance(raw_assignments, list):
        raise ModelCallError("Topic-lifter output missing assignments list")

    claim_ids_set = set(claim_ids)
    assignments: dict[str, str] = {}
    for item in raw_assignments:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id", "")).strip()
        topic_slug = str(item.get("topic_slug", "")).strip()
        if claim_id not in claim_ids_set:
            logger.debug("Skipping unrecognised claim_id from model: %s", claim_id)
            continue
        if claim_id in assignments:
            continue  # keep first assignment, skip duplicates
        if topic_slug not in allowed_slugs:
            logger.warning(
                "Skipping unknown topic_slug from model assignment: claim_id=%s topic_slug=%s",
                claim_id,
                topic_slug,
            )
            continue
        assignments[claim_id] = topic_slug

    missing = [cid for cid in claim_ids if cid not in assignments]
    if missing:
        logger.warning(
            "Topic lifter missed %d/%d claims; filling with heuristic",
            len(missing),
            len(claim_ids),
        )
        claim_lookup = {str(row[0]): row for row in batch_claims}
        for cid in missing:
            row = claim_lookup.get(cid)
            if row:
                assignments[cid] = detect_topic(f"{row[1]} {row[2]} {row[3]}", topics_cfg)

    model_name = str(model_result.get("model_used", "")).strip() or TOPIC_LIFTER_STAGE
    route_suffix = "+partial-heuristic" if missing else ""
    return assignments, f"{TOPIC_LIFTER_STAGE}:{model_name}{route_suffix}"


def assign_topics_fallback(
    batch_claims: list[tuple], topics_cfg: dict[str, list[str]]
) -> tuple[dict[str, str], str]:
    assignments: dict[str, str] = {}
    for claim_id, headline, problem, solution in batch_claims:
        text = f"{headline} {problem} {solution}"
        assignments[str(claim_id)] = detect_topic(text, topics_cfg)
    return assignments, "heuristic-fallback"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env_file(Path(".env"))
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    config_path = Path(os.getenv("RULES_ENGINE_CONFIG", DEFAULT_CONFIG_PATH))

    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}", file=sys.stderr)
        return 2
    if not config_path.exists():
        print(f"Rules config not found: {config_path}", file=sys.stderr)
        return 2

    cfg = read_config(config_path)
    topics_cfg = cfg.get("topics", {})

    conn = sqlite3.connect(sqlite_path)
    init_topic_tables(conn)
    claims = read_claims(conn)
    if not claims:
        print("No claims found. Run extract_claims.py first.", file=sys.stderr)
        conn.close()
        return 2

    now = now_iso()
    claim_topics: list[tuple[str, str, str]] = []
    topic_claims: dict[str, list[str]] = {}
    topic_routes: dict[str, set[str]] = {}
    model_batch_count = 0
    fallback_batch_count = 0
    failfast_switch_count = 0
    stage_started = time.monotonic()
    stage_timeout_seconds = env_int("STAGE_TIMEOUT_SECONDS", 0, minimum=0)
    timeout_buffer_seconds = env_int("TOPIC_LIFTER_TIMEOUT_BUFFER_SECONDS", 30, minimum=0)
    failfast_on_timeout = env_bool("TOPIC_LIFTER_FAILFAST_ON_TIMEOUT", default=True)
    model_budget_exhausted = False

    batch_size = effective_batch_size()
    batches = chunk_claims(claims=claims, batch_size=batch_size)
    emit_progress(
        "lift_topics",
        "batch_plan",
        total_batches=len(batches),
        batch_size=batch_size,
        total_claims=len(claims),
    )
    for idx, batch in enumerate(batches, start=1):
        batch_started = time.monotonic()
        used_fallback = False
        batch_claim_ids = [str(row[0]) for row in batch]
        emit_progress(
            "lift_topics",
            "batch_start",
            index=batch_index(idx, len(batches)),
            claim_ids=",".join(batch_claim_ids),
        )

        elapsed_since_stage_start = time.monotonic() - stage_started
        if stage_timeout_seconds > 0 and elapsed_since_stage_start >= max(
            0, stage_timeout_seconds - timeout_buffer_seconds
        ):
            model_budget_exhausted = True

        if model_budget_exhausted:
            assignments, model_route_used = assign_topics_fallback(
                batch_claims=batch, topics_cfg=topics_cfg
            )
            used_fallback = True
            failfast_switch_count += 1
            if failfast_switch_count == 1:
                logger.warning(
                    "Switching topic lifter to heuristic fallback for remaining batches: "
                    "elapsed=%.1fs timeout=%ss buffer=%ss",
                    elapsed_since_stage_start,
                    stage_timeout_seconds,
                    timeout_buffer_seconds,
                )
        else:
            try:
                assignments, model_route_used = assign_topics_with_model(
                    batch_claims=batch, topics_cfg=topics_cfg
                )
            except ModelCallError as exc:
                logger.warning("Topic-lifter model call failed; using fallback detection: %s", exc)
                assignments, model_route_used = assign_topics_fallback(
                    batch_claims=batch, topics_cfg=topics_cfg
                )
                used_fallback = True
                if failfast_on_timeout and "timed out" in str(exc).lower():
                    model_budget_exhausted = True
                    logger.warning(
                        "Timeout failfast activated for topic_lifter; "
                        "remaining batches will use heuristic fallback."
                    )
        batch_elapsed_ms = elapsed_ms(batch_started)
        if used_fallback:
            fallback_batch_count += 1
        else:
            model_batch_count += 1
        emit_progress(
            "lift_topics",
            "batch_done",
            index=batch_index(idx, len(batches)),
            claims=len(batch),
            mode="fallback" if used_fallback else "model",
            route=model_route_used,
            claim_ids=",".join(batch_claim_ids),
            elapsed_ms=batch_elapsed_ms,
        )

        for claim_id, _, _, _ in batch:
            slug = assignments.get(str(claim_id), "misc")
            claim_topics.append((str(claim_id), slug, model_route_used))
            topic_claims.setdefault(slug, []).append(str(claim_id))
            topic_routes.setdefault(slug, set()).add(model_route_used)

    for slug, claim_ids in topic_claims.items():
        label = label_for_slug(slug)
        why = why_it_matters_for_slug(slug)
        horizon = time_horizon_for_count(len(claim_ids))
        keywords = topics_cfg.get(slug, [])
        topic_id = slug
        route_used = "|".join(sorted(topic_routes.get(slug, {"heuristic-fallback"})))
        conn.execute(
            """
            INSERT OR REPLACE INTO topic_clusters (
                topic_id, parent_topic_slug, parent_topic_label,
                normalized_topic_slug, normalized_topic_label,
                curation_notes, curator_model_route_used,
                why_it_matters, time_horizon, claim_count,
                keywords_json, model_route_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                slug,
                label,
                slug,
                label,
                "",
                "",
                why,
                horizon,
                len(claim_ids),
                json.dumps(keywords, ensure_ascii=True),
                route_used,
                now,
            ),
        )

    for claim_id, topic_id, model_route_used in claim_topics:
        conn.execute(
            """
            INSERT OR REPLACE INTO claim_topic_map (
                claim_id, topic_id, model_route_used, created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (claim_id, topic_id, model_route_used, now),
        )

    conn.commit()
    misc_count = len(topic_claims.get("misc", []))
    misc_ratio = misc_count / max(1, len(claims))
    if misc_ratio > 0.20:
        logger.warning(
            "Topic quality gate warning: misc ratio %.2f exceeds 0.20 threshold",
            misc_ratio,
        )
    conn.close()

    emit_progress("lift_topics", "claims_processed", total=len(claims))
    emit_progress(
        "lift_topics",
        "batch_summary",
        model_batches=model_batch_count,
        fallback_batches=fallback_batch_count,
    )
    emit_progress("lift_topics", "topics_created", total=len(topic_claims))
    emit_progress("lift_topics", "misc_ratio", value=f"{misc_ratio:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
