#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from daily_blog.core.env import load_env_file
from daily_blog.enrichment.helpers import normalize_url

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
DEFAULT_CONFIG_PATH = "./config/rules-engine.json"
DEFAULT_BOARD_PATH = "./data/daily_board.md"


@dataclass
class Mention:
    entry_id: str
    source: str
    feed_url: str
    title: str
    url: str
    published: str
    summary: str
    fetched_at: str


def parse_dt(value: str) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass

    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def read_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def init_scoring_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_items (
            canonical_key TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            source TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            seen_count INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_scores (
            run_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            novelty_status TEXT NOT NULL,
            novelty_score REAL NOT NULL,
            recency_score REAL NOT NULL,
            corroboration_score REAL NOT NULL,
            source_diversity_score REAL NOT NULL,
            actionability_score REAL NOT NULL,
            final_score REAL NOT NULL,
            rank_index INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, entry_id)
        )
        """
    )
    conn.commit()


def read_mentions(conn: sqlite3.Connection) -> list[Mention]:
    rows = conn.execute(
        """
        SELECT entry_id, source, feed_url, title, url, published, summary, fetched_at
        FROM mentions
        ORDER BY fetched_at DESC
        """
    ).fetchall()
    return [Mention(*row) for row in rows]


def topic_for_text(text: str, topics_cfg: dict) -> str:
    lower = text.lower()
    for topic, keywords in topics_cfg.items():
        for kw in keywords:
            if kw.lower() in lower:
                return topic
    return "misc"


def actionability_score(text: str, keywords: list[str]) -> float:
    lower = text.lower()
    matches = 0
    for kw in keywords:
        if kw.lower() in lower:
            matches += 1
    if matches == 0:
        return 0.2
    return min(1.0, 0.2 + 0.2 * matches)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def days_ago(dt: datetime) -> float:
    now = datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def select_deduped_mentions(
    mentions: list[Mention], min_title_length: int, blocked_keywords: list[str]
) -> list[Mention]:
    by_key: dict[str, Mention] = {}
    for m in mentions:
        title = (m.title or "").strip()
        if len(title) < min_title_length:
            continue
        lower = title.lower()
        skip = False
        for bad in blocked_keywords:
            if bad.lower() in lower:
                skip = True
                break
        if skip:
            continue

        canonical = normalize_url(m.url) or m.entry_id
        existing = by_key.get(canonical)
        if existing is None:
            by_key[canonical] = m
            continue
        if parse_dt(m.fetched_at) > parse_dt(existing.fetched_at):
            by_key[canonical] = m
    return list(by_key.values())


def canonical_history(conn: sqlite3.Connection, canonical_key: str) -> tuple[datetime | None, int]:
    row = conn.execute(
        "SELECT last_seen_at, seen_count FROM canonical_items WHERE canonical_key = ?",
        (canonical_key,),
    ).fetchone()
    if not row:
        return None, 0
    last_seen = parse_dt(row[0])
    return last_seen, int(row[1])


def novelty_state(last_seen: datetime | None, cfg: dict) -> tuple[str, float]:
    if last_seen is None:
        return "novel", float(cfg["novel_score"])

    age_days = days_ago(last_seen)
    if age_days <= float(cfg["novel_days"]):
        return "recent", float(cfg["recent_score"])
    if age_days <= float(cfg["recent_days"]):
        return "recent", float(cfg["recent_score"])
    return "stale", float(cfg["stale_score"])


def score_mentions(conn: sqlite3.Connection, mentions: list[Mention], cfg: dict) -> list[dict]:
    topics_cfg = cfg["topics"]
    actionability_keywords = cfg["actionability_keywords"]
    weights = cfg["weights"]

    topic_counts: dict[str, int] = {}
    topic_sources: dict[str, set[str]] = {}
    decorated: list[dict] = []

    for m in mentions:
        text = f"{m.title} {m.summary}"
        topic = topic_for_text(text, topics_cfg)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        topic_sources.setdefault(topic, set()).add(m.source)
        decorated.append({"mention": m, "topic": topic})

    max_topic_count = max(topic_counts.values()) if topic_counts else 1

    out: list[dict] = []
    for d in decorated:
        m = d["mention"]
        topic = d["topic"]
        canonical = normalize_url(m.url) or m.entry_id
        last_seen, seen_count = canonical_history(conn, canonical)
        novelty_status, novelty = novelty_state(last_seen, cfg["novelty"])

        recency = clamp(1.0 - (days_ago(parse_dt(m.published or m.fetched_at)) / 7.0))
        corroboration = clamp(topic_counts[topic] / max_topic_count)
        source_div = clamp(len(topic_sources[topic]) / max(1, len({x.source for x in mentions})))
        actionability = actionability_score(f"{m.title} {m.summary}", actionability_keywords)

        final = (
            float(weights["novelty"]) * novelty
            + float(weights["recency"]) * recency
            + float(weights["corroboration"]) * corroboration
            + float(weights["source_diversity"]) * source_div
            + float(weights["actionability"]) * actionability
        )

        if seen_count > 0:
            final -= min(0.2, seen_count * 0.02)

        out.append(
            {
                "entry_id": m.entry_id,
                "title": m.title,
                "url": m.url,
                "source": m.source,
                "topic": topic,
                "canonical_key": canonical,
                "novelty_status": novelty_status,
                "novelty_score": clamp(novelty),
                "recency_score": clamp(recency),
                "corroboration_score": clamp(corroboration),
                "source_diversity_score": clamp(source_div),
                "actionability_score": clamp(actionability),
                "final_score": clamp(final),
            }
        )

    out.sort(key=lambda x: x["final_score"], reverse=True)
    return out


def apply_selection(ranked: list[dict], cfg: dict) -> list[dict]:
    max_candidates = int(cfg["hard_rules"]["max_candidates"])
    max_per_topic = int(cfg["hard_rules"]["max_per_topic"])
    min_final = float(cfg["hard_rules"]["min_final_score"])

    selected: list[dict] = []
    topic_counts: dict[str, int] = {}

    for item in ranked:
        if item["final_score"] < min_final:
            continue
        topic = item["topic"]
        count = topic_counts.get(topic, 0)
        if count >= max_per_topic:
            continue
        selected.append(item)
        topic_counts[topic] = count + 1
        if len(selected) >= max_candidates:
            break

    return selected


def upsert_canonical_items(conn: sqlite3.Connection, selected: list[dict], now_iso: str) -> None:
    for item in selected:
        key = item["canonical_key"]
        row = conn.execute(
            "SELECT first_seen_at, seen_count FROM canonical_items WHERE canonical_key = ?",
            (key,),
        ).fetchone()
        if row:
            first_seen = row[0]
            seen_count = int(row[1]) + 1
        else:
            first_seen = now_iso
            seen_count = 1
        conn.execute(
            """
            INSERT INTO canonical_items (
                canonical_key, title, url, source, first_seen_at, last_seen_at, seen_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title = excluded.title,
                url = excluded.url,
                source = excluded.source,
                last_seen_at = excluded.last_seen_at,
                seen_count = excluded.seen_count
            """,
            (
                key,
                item["title"],
                item["url"],
                item["source"],
                first_seen,
                now_iso,
                seen_count,
            ),
        )
    conn.commit()


def persist_scores(
    conn: sqlite3.Connection, run_id: str, selected: list[dict], now_iso: str
) -> None:
    for idx, item in enumerate(selected, start=1):
        conn.execute(
            """
            INSERT INTO candidate_scores (
                run_id, entry_id, topic, novelty_status,
                novelty_score, recency_score, corroboration_score,
                source_diversity_score, actionability_score,
                final_score, rank_index, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                item["entry_id"],
                item["topic"],
                item["novelty_status"],
                item["novelty_score"],
                item["recency_score"],
                item["corroboration_score"],
                item["source_diversity_score"],
                item["actionability_score"],
                item["final_score"],
                idx,
                now_iso,
            ),
        )
    conn.commit()


def write_board(path: Path, run_id: str, selected: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Daily Topic Board ({run_id})",
        "",
        f"Candidates: {len(selected)}",
        "",
    ]
    for idx, item in enumerate(selected, start=1):
        lines.append(f"## {idx}. {item['title']}")
        lines.append(f"- score: {item['final_score']:.3f}")
        lines.append(f"- topic: {item['topic']}")
        lines.append(f"- novelty: {item['novelty_status']}")
        lines.append(f"- source: {item['source']}")
        lines.append(f"- url: {item['url']}")
        lines.append(
            "- components: "
            f"novelty={item['novelty_score']:.2f}, "
            f"recency={item['recency_score']:.2f}, "
            f"corroboration={item['corroboration_score']:.2f}, "
            f"source_diversity={item['source_diversity_score']:.2f}, "
            f"actionability={item['actionability_score']:.2f}"
        )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    load_env_file(Path(".env"))

    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    config_path = Path(os.getenv("RULES_ENGINE_CONFIG", DEFAULT_CONFIG_PATH))
    board_path = Path(os.getenv("SCORE_BOARD_PATH", DEFAULT_BOARD_PATH))

    try:
        cfg = read_config(config_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(sqlite_path)
    init_scoring_tables(conn)
    mentions = read_mentions(conn)
    if not mentions:
        print("No mentions found. Run ingest first.", file=sys.stderr)
        conn.close()
        return 2

    rules = cfg["hard_rules"]
    deduped = select_deduped_mentions(
        mentions,
        int(rules["min_title_length"]),
        list(rules["blocked_title_keywords"]),
    )
    ranked = score_mentions(conn, deduped, cfg)
    selected = apply_selection(ranked, cfg)

    now_iso = datetime.now(timezone.utc).isoformat()
    run_id = os.getenv("RUN_ID", "").strip() or datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    persist_scores(conn, run_id, selected, now_iso)
    upsert_canonical_items(conn, selected, now_iso)
    write_board(board_path, run_id, selected)
    conn.close()

    print(f"Run ID: {run_id}")
    print(f"Mentions read: {len(mentions)}")
    print(f"Mentions after hard rules + dedupe: {len(deduped)}")
    print(f"Selected candidates: {len(selected)}")
    print(f"Board: {board_path}")
    print(f"Config: {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
