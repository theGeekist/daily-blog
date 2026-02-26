#!/usr/bin/env python3
import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from daily_blog.config import load_app_config
from daily_blog.core.env import load_env_file
from daily_blog.core.time_utils import now_iso
from orchestrator_utils import ModelCallError, call_model

TOPIC_CURATOR_STAGE = "topic_curator"
DEFAULT_BATCH_SIZE = 8

logger = logging.getLogger(__name__)


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower().strip())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "misc"


def fallback_label(slug: str) -> str:
    s = slug.strip().lower()
    special = {
        "ai": "AI",
        "ml": "ML",
        "llm": "LLM",
        "web": "Web",
        "misc": "General Engineering",
    }
    if s in special:
        return special[s]
    return s.replace("-", " ").replace("_", " ").title()


def init_topic_curation_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(topic_clusters)").fetchall()
        if len(row) > 1
    }
    if "normalized_topic_slug" not in columns:
        conn.execute(
            "ALTER TABLE topic_clusters ADD COLUMN normalized_topic_slug TEXT NOT NULL DEFAULT ''"
        )
    if "normalized_topic_label" not in columns:
        conn.execute(
            "ALTER TABLE topic_clusters ADD COLUMN normalized_topic_label TEXT NOT NULL DEFAULT ''"
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


def build_schema(topic_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["topics"],
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "topic_id",
                        "normalized_topic_slug",
                        "normalized_topic_label",
                        "curation_notes",
                    ],
                    "properties": {
                        "topic_id": {"type": "string", "enum": topic_ids},
                        "normalized_topic_slug": {"type": "string"},
                        "normalized_topic_label": {"type": "string"},
                        "curation_notes": {"type": "string"},
                    },
                },
            }
        },
    }


def build_prompt(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=True, indent=2)
    return "\n".join(
        [
            "You are a topic normalization and curation engine.",
            "",
            "Task:",
            "- Preserve the same number of topics and keep the original topic_id unchanged.",
            "- Produce clean, human-readable display labels for dashboard use.",
            "- Keep normalized_topic_slug short and stable (lowercase kebab-case).",
            "- Avoid noisy variants (for example: Ai -> ai, web -> web, "
            "long misc labels -> general-engineering).",
            "- Return only valid JSON matching schema.",
            "",
            "Input topics:",
            payload,
            "",
            "Output shape:",
            '{"topics":[{"topic_id":"...","normalized_topic_slug":"...","normalized_topic_label":"...","curation_notes":"..."}]}',
        ]
    )


def model_curate(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, str]], str]:
    topic_ids = [str(r["topic_id"]) for r in rows]
    schema = build_schema(topic_ids)
    prompt = build_prompt(rows)
    result = call_model(TOPIC_CURATOR_STAGE, prompt, schema=schema)
    payload = result.get("content", {})
    if not isinstance(payload, dict):
        raise ModelCallError("Topic curator returned non-object payload")
    topics = payload.get("topics")
    if not isinstance(topics, list):
        raise ModelCallError("Topic curator payload missing topics list")

    mapped: dict[str, dict[str, str]] = {}
    for item in topics:
        if not isinstance(item, dict):
            raise ModelCallError("Topic curator list item must be object")
        topic_id = str(item.get("topic_id", "")).strip()
        if topic_id not in topic_ids:
            raise ModelCallError(f"Unknown topic_id in curator output: {topic_id}")
        slug = slugify(str(item.get("normalized_topic_slug", "")))
        label = str(item.get("normalized_topic_label", "")).strip() or fallback_label(slug)
        notes = str(item.get("curation_notes", "")).strip()
        mapped[topic_id] = {
            "normalized_topic_slug": slug,
            "normalized_topic_label": label,
            "curation_notes": notes,
        }

    missing = [topic_id for topic_id in topic_ids if topic_id not in mapped]
    if missing:
        raise ModelCallError(f"Missing curated topics for topic_ids: {missing}")
    model_used = str(result.get("model_used") or TOPIC_CURATOR_STAGE)
    return mapped, f"{TOPIC_CURATOR_STAGE}:{model_used}"


def fallback_curate(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, str]], str]:
    mapped: dict[str, dict[str, str]] = {}
    for row in rows:
        topic_id = str(row["topic_id"])
        parent_slug = str(row.get("parent_topic_slug") or topic_id)
        normalized_slug = slugify(parent_slug)
        mapped[topic_id] = {
            "normalized_topic_slug": normalized_slug,
            "normalized_topic_label": fallback_label(normalized_slug),
            "curation_notes": "heuristic normalization",
        }
    return mapped, "topic_curator:heuristic-fallback"


def chunk_topics(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    if batch_size <= 0:
        return [rows]
    return [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env_file(Path(".env"))
    project_root = Path(__file__).resolve().parent
    app_cfg = load_app_config(project_root=project_root, environ=os.environ)
    sqlite_path = app_cfg.paths.sqlite_path
    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(sqlite_path)
    init_topic_curation_columns(conn)
    force_recurate = app_cfg.topics.force_recurate
    where_sql = "" if force_recurate else "WHERE tc.normalized_topic_slug = ''"
    rows = conn.execute(
        (
            """
        SELECT tc.topic_id, tc.parent_topic_slug, tc.parent_topic_label,
               tc.claim_count, tc.why_it_matters,
               GROUP_CONCAT(c.headline, ' | ') AS claim_headlines
        FROM topic_clusters tc
        LEFT JOIN claim_topic_map ctm ON ctm.topic_id = tc.topic_id
        LEFT JOIN claims c ON c.claim_id = ctm.claim_id
        """
            + where_sql
            + """
        GROUP BY tc.topic_id, tc.parent_topic_slug, tc.parent_topic_label,
                 tc.claim_count, tc.why_it_matters
        ORDER BY tc.claim_count DESC
        """
        )
    ).fetchall()
    if not rows:
        if force_recurate:
            print("No topics found. Run lift_topics.py first.", file=sys.stderr)
            conn.close()
            return 2
        print("No uncurated topics found. Skipping normalization.")
        conn.close()
        return 0

    topic_rows = [
        {
            "topic_id": str(topic_id),
            "parent_topic_slug": str(parent_slug or ""),
            "parent_topic_label": str(parent_label or ""),
            "claim_count": int(claim_count or 0),
            "why_it_matters": str(why or ""),
            "claim_headlines": str(claim_headlines or ""),
        }
        for topic_id, parent_slug, parent_label, claim_count, why, claim_headlines in rows
    ]

    now = now_iso()
    batch_size = app_cfg.topics.curator_batch_size
    routes_used: set[str] = set()
    for batch in chunk_topics(topic_rows, batch_size=batch_size):
        try:
            curated, route_used = model_curate(batch)
        except ModelCallError as exc:
            logger.warning(
                "Topic curator model call failed for batch size=%d; "
                "using fallback normalization: %s",
                len(batch),
                exc,
            )
            curated = {}
            route_used = ""
            for row in batch:
                try:
                    single_curated, single_route = model_curate([row])
                    curated.update(single_curated)
                    route_used = route_used or single_route
                except ModelCallError as single_exc:
                    logger.warning(
                        "Topic curator single-item model call failed for topic_id=%s: %s",
                        row.get("topic_id", ""),
                        single_exc,
                    )
                    fallback_one, fallback_route = fallback_curate([row])
                    curated.update(fallback_one)
                    route_used = route_used or fallback_route
        routes_used.add(route_used)

        for row in batch:
            topic_id = row["topic_id"]
            item = curated.get(topic_id, {})
            conn.execute(
                """
                UPDATE topic_clusters
                SET normalized_topic_slug = ?,
                    normalized_topic_label = ?,
                    curation_notes = ?,
                    curator_model_route_used = ?,
                    created_at = ?
                WHERE topic_id = ?
                """,
                (
                    str(
                        item.get("normalized_topic_slug") or slugify(str(row["parent_topic_slug"]))
                    ),
                    str(
                        item.get("normalized_topic_label")
                        or fallback_label(str(row["parent_topic_slug"]))
                    ),
                    str(item.get("curation_notes") or ""),
                    route_used,
                    now,
                    topic_id,
                ),
            )

    conn.commit()
    conn.close()
    print(f"Topics curated: {len(topic_rows)}")
    routes_text = "|".join(sorted(routes_used)) if routes_used else "n/a"
    print(f"Curator route: {routes_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
