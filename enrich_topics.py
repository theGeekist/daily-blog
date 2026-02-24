#!/usr/bin/env python3
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

from daily_blog.core.env import load_env_file
from daily_blog.core.time_utils import now_iso
from daily_blog.enrichment.discussion import harvest_discussion_receipts
from daily_blog.enrichment.fetch import discover_web_sources, verify_source_fetch
from daily_blog.enrichment.helpers import (
    credibility_for_domain,
    credibility_rank,
    default_query_terms,
    domain_for_url,
    filter_sources_for_quality,
    normalize_url,
    parse_keywords_json,
)
from daily_blog.enrichment.model_io import fetch_discussion_signals, fetch_model_sources
from daily_blog.enrichment.store import (
    enrichment_has_model_route,
    init_discussion_receipts_table,
    init_enrichment_table,
    topic_clusters_has_normalized_label,
    upsert_discussion_receipt,
    upsert_enrichment_source,
)

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
ENRICHMENT_STAGE = "enrichment"


def _coerce_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env_file(Path(".env"))
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(sqlite_path)
    init_enrichment_table(conn)
    init_discussion_receipts_table(conn)
    has_model_route_column = enrichment_has_model_route(conn)
    has_normalized_label = topic_clusters_has_normalized_label(conn)

    if has_normalized_label:
        topic_rows = conn.execute(
            """
            SELECT topic_id,
                   COALESCE(NULLIF(normalized_topic_label, ''), parent_topic_label) AS topic_label,
                   keywords_json
            FROM topic_clusters
            """
        ).fetchall()
    else:
        topic_rows = conn.execute(
            """
            SELECT topic_id, parent_topic_label AS topic_label, keywords_json
            FROM topic_clusters
            """
        ).fetchall()
    if not topic_rows:
        print("No topics found. Run lift_topics.py first.", file=sys.stderr)
        conn.close()
        return 2

    rows_written = 0
    now = now_iso()
    timeout_seconds = int(os.getenv("ENRICH_FETCH_TIMEOUT_SECONDS", "10"))
    discovered_limit = int(os.getenv("ENRICH_DISCOVER_LIMIT", "10"))
    max_known_claim_urls = int(os.getenv("ENRICH_MAX_KNOWN_CLAIM_URLS", "24"))
    max_topics = int(os.getenv("ENRICH_MAX_TOPICS", "0"))
    processed_topics = 0
    for topic_id, label, keywords_json in topic_rows:
        if max_topics > 0 and processed_topics >= max_topics:
            break
        processed_topics += 1
        keywords = parse_keywords_json(keywords_json)
        query_terms = default_query_terms(label, keywords)
        claim_urls = conn.execute(
            """
            SELECT c.sources_json
            FROM claims c
            JOIN claim_topic_map m ON m.claim_id = c.claim_id
            WHERE m.topic_id = ?
            """,
            (topic_id,),
        ).fetchall()

        candidate_urls: list[str] = []
        for (sources_json,) in claim_urls:
            try:
                urls = json.loads(sources_json)
            except json.JSONDecodeError:
                urls = []
            for u in urls:
                if isinstance(u, str) and u.startswith("http"):
                    candidate_urls.append(u)

        known_sources: list[str] = []
        source_map: dict[str, dict[str, str | int]] = {}
        for raw_url in candidate_urls:
            url = normalize_url(raw_url)
            if not url or url in source_map:
                continue
            known_sources.append(url)
            domain = domain_for_url(url)
            source_map[url] = {
                "url": url,
                "domain": domain,
                "stance": "neutral",
                "credibility_guess": credibility_for_domain(domain),
                "fetched_ok": 1 if verify_source_fetch(url, timeout_seconds=timeout_seconds) else 0,
            }
            if len(known_sources) >= max_known_claim_urls:
                break

        receipts = harvest_discussion_receipts(known_sources)
        discussion_signals, discussion_route_used = fetch_discussion_signals(
            topic_id=topic_id,
            topic_label=label,
            query_terms=query_terms,
            receipts=receipts,
        )
        for term in discussion_signals["query_terms"]:
            lowered = term.lower()
            if lowered not in query_terms:
                query_terms.append(lowered)
        query_terms = query_terms[:30]

        discovered_urls = discover_web_sources(
            topic_label=label,
            query_terms=query_terms,
            limit=discovered_limit,
        )
        for discovered in discovered_urls:
            if discovered in source_map:
                continue
            domain = domain_for_url(discovered)
            guessed_credibility = credibility_for_domain(domain)
            if credibility_rank(guessed_credibility) < 2:
                continue
            source_map[discovered] = {
                "url": discovered,
                "domain": domain,
                "stance": "neutral",
                "credibility_guess": guessed_credibility,
                "fetched_ok": 1
                if verify_source_fetch(discovered, timeout_seconds=timeout_seconds)
                else 0,
            }

        model_sources, model_route_used = fetch_model_sources(
            topic_id=topic_id,
            topic_label=label,
            keywords=keywords,
            known_sources=known_sources,
            query_terms=query_terms,
        )

        for src in model_sources:
            url = src["url"]
            if credibility_rank(src["credibility_guess"]) < 2:
                continue
            existing = source_map.get(url)
            if existing is None:
                source_map[url] = {
                    "url": url,
                    "domain": src["domain"],
                    "stance": src["stance"],
                    "credibility_guess": src["credibility_guess"],
                    "fetched_ok": 1
                    if verify_source_fetch(url, timeout_seconds=timeout_seconds)
                    else 0,
                }
                continue

            if verify_source_fetch(url, timeout_seconds=timeout_seconds):
                existing["fetched_ok"] = 1
            if str(existing.get("stance", "neutral")) == "neutral" and src["stance"] != "neutral":
                existing["stance"] = src["stance"]

            current_cred = str(existing.get("credibility_guess", "low"))
            if credibility_rank(src["credibility_guess"]) > credibility_rank(current_cred):
                existing["credibility_guess"] = src["credibility_guess"]

        source_map = filter_sources_for_quality(source_map, min_credible_count=3)
        conn.execute("DELETE FROM enrichment_sources WHERE topic_id = ?", (topic_id,))
        conn.execute("DELETE FROM discussion_receipts WHERE topic_id = ?", (topic_id,))
        query_terms_json = json.dumps(query_terms, ensure_ascii=True)
        for source in source_map.values():
            upsert_enrichment_source(
                conn=conn,
                has_model_route_column=has_model_route_column,
                topic_id=topic_id,
                query_terms_json=query_terms_json,
                source=source,
                now=now,
                model_route_used=model_route_used,
            )
            rows_written += 1
        problem_json = json.dumps(discussion_signals["problem_statements"], ensure_ascii=True)
        solution_json = json.dumps(discussion_signals["solution_statements"], ensure_ascii=True)
        for receipt in receipts:
            source_url = str(receipt.get("source_url", ""))
            if not source_url:
                continue
            upsert_discussion_receipt(
                conn=conn,
                topic_id=str(topic_id),
                source_url=source_url,
                platform=str(receipt.get("platform", "")),
                query_used=str(receipt.get("query_used", "")),
                receipt_text=str(receipt.get("receipt_text", "")),
                comment_count=_coerce_int(receipt.get("comment_count", 0)),
                problem_statements_json=problem_json,
                solution_statements_json=solution_json,
                model_route_used=discussion_route_used,
                now=now,
            )

    conn.commit()
    conn.close()
    print(f"Enrichment rows written: {rows_written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
