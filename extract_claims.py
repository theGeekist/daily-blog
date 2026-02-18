#!/usr/bin/env python3
import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator_utils import ModelCallError, call_model

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
EXTRACTOR_STAGE = "extractor"

logger = logging.getLogger(__name__)

CLAIM_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "headline",
        "who_cares",
        "problem_pressure",
        "proposed_solution",
        "evidence_type",
        "sources",
    ],
    "properties": {
        "headline": {"type": "string"},
        "who_cares": {"type": "string"},
        "problem_pressure": {"type": "string"},
        "proposed_solution": {"type": "string"},
        "evidence_type": {"type": "string", "enum": ["data", "link", "anecdote"]},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_html(text: str) -> str:
    if not text:
        return ""
    stripped = re.sub(r"<[^>]+>", " ", text)
    stripped = html.unescape(stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def detect_evidence_type(title: str, summary: str) -> str:
    blob = f"{title} {summary}".lower()
    if "study" in blob or "paper" in blob or "research" in blob or "benchmark" in blob:
        return "data"
    if "http" in blob or "link" in blob or "github" in blob:
        return "link"
    return "anecdote"


def infer_audience(title: str, summary: str) -> str:
    blob = f"{title} {summary}".lower()
    if "react" in blob or "frontend" in blob or "javascript" in blob:
        return "web engineers"
    if "ml" in blob or "llm" in blob or "model" in blob:
        return "ml practitioners"
    if "sales" in blob or "growth" in blob:
        return "operators and founders"
    return "software engineers"


def infer_problem(title: str, summary: str) -> str:
    text = strip_html(f"{title}. {summary}")
    if not text:
        return "Insufficient context in source feed"
    return text[:220]


def infer_solution(title: str, summary: str) -> str:
    blob = strip_html(f"{title}. {summary}")
    if "how" in blob.lower() or "guide" in blob.lower() or "playbook" in blob.lower():
        return "Apply the described workflow and validate with practical checks"
    return "Investigate the claim, collect corroborating evidence, and document trade-offs"


def init_claims_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            entry_id TEXT NOT NULL,
            headline TEXT NOT NULL,
            who_cares TEXT NOT NULL,
            problem_pressure TEXT NOT NULL,
            proposed_solution TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            sources_json TEXT NOT NULL,
            model_route_used TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def read_mentions(conn: sqlite3.Connection, limit: int = 300) -> list[tuple]:
    return conn.execute(
        """
        SELECT m.entry_id, m.title, m.url, m.summary
        FROM mentions m
        LEFT JOIN claims c ON c.entry_id = m.entry_id
        WHERE c.entry_id IS NULL
        ORDER BY m.fetched_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def make_claim_id(entry_id: str) -> str:
    return hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:20]


def build_extraction_prompt(title: str, summary: str) -> str:
    clean_title = strip_html(title) or "Untitled mention"
    clean_summary = strip_html(summary) or ""
    return (
        """You are an extraction engine for content claims.

Task:
- Read the mention metadata.
- Extract one practical claim and supporting fields.
- Return ONLY valid JSON (no prose, no markdown).

Required output JSON fields:
- headline (string)
- who_cares (string)
- problem_pressure (string)
- proposed_solution (string)
- evidence_type (string enum: data|link|anecdote)
- sources (array of source URL strings)

Quality requirements:
- Keep headline specific and concise.
- who_cares must identify a concrete audience segment.
- Do not invent unsupported facts.
- If uncertainty is high, still provide best-effort extraction from given content.

Mention title:
"""
        + clean_title
        + """

Mention summary:
"""
        + clean_summary
    )


def normalize_sources(raw_sources: Any, fallback_url: str) -> list[str]:
    sources: list[str] = []
    if isinstance(raw_sources, list):
        for item in raw_sources:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    sources.append(normalized)
    if not sources:
        fallback = (fallback_url or "").strip()
        if fallback:
            sources.append(fallback)
    return sources


def extract_claim(
    entry_id: str, title: str, url: str, summary: str
) -> tuple[dict[str, str | list[str]], str]:
    prompt = build_extraction_prompt(title=title, summary=summary)
    try:
        model_result = call_model(
            stage_name=EXTRACTOR_STAGE,
            prompt=prompt,
            schema=CLAIM_EXTRACTION_SCHEMA,
        )
        payload = model_result.get("content", {})
        if not isinstance(payload, dict):
            raise ModelCallError("Model output content must be a JSON object")

        evidence = payload.get("evidence_type")
        if evidence not in {"data", "link", "anecdote"}:
            evidence = "anecdote"

        extracted = {
            "headline": strip_html(str(payload.get("headline", ""))).strip(),
            "who_cares": strip_html(str(payload.get("who_cares", ""))).strip(),
            "problem_pressure": strip_html(str(payload.get("problem_pressure", ""))).strip(),
            "proposed_solution": strip_html(str(payload.get("proposed_solution", ""))).strip(),
            "evidence_type": evidence,
            "sources": normalize_sources(payload.get("sources"), fallback_url=url),
        }
        model_name = str(model_result.get("model_used", "")).strip() or EXTRACTOR_STAGE
        return extracted, f"{EXTRACTOR_STAGE}:{model_name}"
    except ModelCallError as exc:
        logger.warning("Model extraction failed for entry_id=%s: %s", entry_id, exc)
        return (
            {
                "headline": strip_html(title) or "Untitled mention",
                "who_cares": infer_audience(title, summary),
                "problem_pressure": infer_problem(title, summary),
                "proposed_solution": infer_solution(title, summary),
                "evidence_type": detect_evidence_type(title, summary),
                "sources": normalize_sources([], fallback_url=url),
            },
            "heuristic-fallback",
        )


def upsert_claims(conn: sqlite3.Connection, rows: list[tuple]) -> int:
    inserted = 0
    for row in rows:
        cur = conn.execute(
            """
            INSERT OR REPLACE INTO claims (
                claim_id, entry_id, headline, who_cares, problem_pressure,
                proposed_solution, evidence_type, sources_json, model_route_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        if cur.rowcount > 0:
            inserted += 1
    conn.commit()
    return inserted


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env_file(Path(".env"))
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(sqlite_path)
    init_claims_table(conn)
    max_mentions = int(os.getenv("EXTRACT_MAX_MENTIONS", "300"))
    mentions = read_mentions(conn, limit=max_mentions)
    now = now_iso()

    rows: list[tuple] = []
    for entry_id, title, url, summary in mentions:
        extracted, model_route_used = extract_claim(
            entry_id=entry_id,
            title=title or "",
            url=url or "",
            summary=summary or "",
        )
        headline = str(extracted.get("headline", "")).strip()
        who_cares = str(extracted.get("who_cares", "")).strip()
        if not headline or not who_cares:
            logger.warning(
                "Skipping entry_id=%s due to quality gate failure (headline/who_cares missing)",
                entry_id,
            )
            continue

        problem = str(extracted.get("problem_pressure", "")).strip() or infer_problem(
            title or "", summary or ""
        )
        solution = str(extracted.get("proposed_solution", "")).strip() or infer_solution(
            title or "", summary or ""
        )
        evidence = str(extracted.get("evidence_type", "")).strip()
        if evidence not in {"data", "link", "anecdote"}:
            evidence = detect_evidence_type(title or "", summary or "")
        sources = json.dumps(
            normalize_sources(extracted.get("sources"), fallback_url=url or ""), ensure_ascii=True
        )
        rows.append(
            (
                make_claim_id(entry_id),
                entry_id,
                headline,
                who_cares,
                problem,
                solution,
                evidence,
                sources,
                model_route_used,
                now,
            )
        )

    count = upsert_claims(conn, rows)
    conn.close()
    print(f"Claims upserted: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
