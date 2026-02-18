#!/usr/bin/env python3
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator_utils import ModelCallError, call_model

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
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


def init_enrichment_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS enrichment_sources (
            topic_id TEXT NOT NULL,
            query_terms_json TEXT NOT NULL,
            domain TEXT NOT NULL,
            url TEXT NOT NULL,
            stance TEXT NOT NULL,
            credibility_guess TEXT NOT NULL,
            fetched_ok INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (topic_id, url)
        )
        """
    )
    conn.commit()


def enrichment_has_model_route(conn: sqlite3.Connection) -> bool:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(enrichment_sources)").fetchall()
        if len(row) > 1
    }
    return "model_route_used" in columns


def topic_clusters_has_normalized_label(conn: sqlite3.Connection) -> bool:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(topic_clusters)").fetchall()
        if len(row) > 1
    }
    return "normalized_topic_label" in columns


def credibility_for_domain(domain: str) -> str:
    medium = {
        "arxiv.org",
        "github.com",
        "docs.python.org",
        "reddit.com",
        "wikipedia.org",
        "stackexchange.com",
    }
    high = {
        "nature.com",
        "science.org",
        "nejm.org",
        "acm.org",
        "ieee.org",
    }
    if domain in high:
        return "high"
    if domain in medium:
        return "medium"
    if domain.endswith(".edu") or domain.endswith(".gov"):
        return "high"
    if domain.endswith(".org"):
        return "medium"
    return "low"


def credibility_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value, 0)


def default_query_terms(label: str, keywords: list[str]) -> list[str]:
    base = [w.strip().lower() for w in label.split() if w.strip()]
    merged = base + [k.lower() for k in keywords]
    deduped: list[str] = []
    seen = set()
    for term in merged:
        if term not in seen:
            seen.add(term)
            deduped.append(term)
    return deduped[:20]


def normalize_url(url: str) -> str:
    trimmed = url.strip()
    if not trimmed:
        return ""
    parsed = urllib.parse.urlparse(trimmed)
    if parsed.scheme not in {"http", "https"}:
        return ""
    netloc = parsed.netloc.lower()
    if not netloc:
        return ""
    normalized = parsed._replace(netloc=netloc, fragment="")
    return normalized.geturl()


def domain_for_url(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().replace("www.", "")


def verify_source_fetch(url: str, timeout_seconds: int = 8) -> bool:
    user_agent = os.getenv(
        "ENRICH_FETCH_USER_AGENT",
        "Mozilla/5.0 (compatible; daily-blog-enrichment/0.2; +https://localhost)",
    )
    retries = int(os.getenv("ENRICH_FETCH_RETRIES", "2"))
    backoff_seconds = float(os.getenv("ENRICH_FETCH_BACKOFF_SECONDS", "0.6"))

    candidates = [url]
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower().replace("www.", "")
    if netloc == "reddit.com" or netloc.endswith(".reddit.com"):
        path = parsed.path
        if "/comments/" in path:
            parts = [p for p in path.split("/") if p]
            post_id = ""
            if "comments" in parts:
                idx = parts.index("comments")
                if idx + 1 < len(parts):
                    post_id = parts[idx + 1]
            if post_id:
                candidates.append(f"https://www.reddit.com/comments/{post_id}.json?limit=1")
        candidates.append(urllib.parse.urlunparse(parsed._replace(netloc="old.reddit.com")))

    seen: set[str] = set()
    deduped_candidates: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped_candidates.append(candidate)

    for candidate in deduped_candidates:
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(
                    candidate,
                    headers={
                        "User-Agent": user_agent,
                        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.8",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                    status_code = int(getattr(response, "status", 200))
                    content_type = str(response.headers.get("Content-Type", "")).lower()
                    allowed_types = (
                        "text/html",
                        "application/json",
                        "application/xhtml+xml",
                        "text/plain",
                        "application/xml",
                    )
                    if status_code < 400 and (
                        not content_type or any(t in content_type for t in allowed_types)
                    ):
                        return True
            except Exception:
                if attempt < retries:
                    time.sleep(backoff_seconds * (attempt + 1))
                continue
    return False


def discover_web_sources(topic_label: str, query_terms: list[str], limit: int = 12) -> list[str]:
    query = " ".join([topic_label] + query_terms[:6]).strip()
    if not query:
        return []

    user_agent = os.getenv(
        "ENRICH_FETCH_USER_AGENT",
        "Mozilla/5.0 (compatible; daily-blog-enrichment/0.2; +https://localhost)",
    )
    timeout_seconds = int(os.getenv("ENRICH_FETCH_TIMEOUT_SECONDS", "10"))
    encoded_query = urllib.parse.quote_plus(query)
    search_urls = [
        f"https://duckduckgo.com/html/?q={encoded_query}",
        f"https://r.jina.ai/http://duckduckgo.com/html/?q={encoded_query}",
    ]

    extracted_urls: list[str] = []
    for search_url in search_urls:
        try:
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.8"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                html = response.read().decode("utf-8", errors="ignore")

            for chunk in html.split('href="'):
                if '"' not in chunk:
                    continue
                href = chunk.split('"', 1)[0]
                candidate = ""
                if "uddg=" in href:
                    parsed = urllib.parse.urlparse(href)
                    qs = urllib.parse.parse_qs(parsed.query)
                    candidate = urllib.parse.unquote_plus(qs.get("uddg", [""])[0])
                elif href.startswith("http://") or href.startswith("https://"):
                    candidate = href

                normalized = normalize_url(candidate)
                if not normalized:
                    continue
                domain = domain_for_url(normalized)
                if domain.endswith("duckduckgo.com"):
                    continue
                extracted_urls.append(normalized)
                if len(extracted_urls) >= limit:
                    break
            if extracted_urls:
                break
        except Exception:
            continue

    deduped: list[str] = []
    seen: set[str] = set()
    for u in extracted_urls:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
        if len(deduped) >= limit:
            break
    return deduped


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


def upsert_enrichment_source(
    conn: sqlite3.Connection,
    has_model_route_column: bool,
    topic_id: str,
    query_terms_json: str,
    source: dict[str, str | int],
    now: str,
    model_route_used: str,
) -> None:
    if has_model_route_column:
        conn.execute(
            """
            INSERT OR REPLACE INTO enrichment_sources (
                topic_id, query_terms_json, domain, url, stance,
                credibility_guess, fetched_ok, created_at, model_route_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                query_terms_json,
                source["domain"],
                source["url"],
                source["stance"],
                source["credibility_guess"],
                source["fetched_ok"],
                now,
                model_route_used,
            ),
        )
        return

    conn.execute(
        """
        INSERT OR REPLACE INTO enrichment_sources (
            topic_id, query_terms_json, domain, url, stance,
            credibility_guess, fetched_ok, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            topic_id,
            query_terms_json,
            source["domain"],
            source["url"],
            source["stance"],
            source["credibility_guess"],
            source["fetched_ok"],
            now,
        ),
    )


def filter_sources_for_quality(
    source_map: dict[str, dict[str, str | int]],
    min_credible_count: int = 3,
) -> dict[str, dict[str, str | int]]:
    high_medium_urls = [
        url
        for url, source in source_map.items()
        if credibility_rank(str(source.get("credibility_guess", "low"))) >= 2
    ]
    if len(high_medium_urls) >= min_credible_count:
        return {url: source_map[url] for url in high_medium_urls}
    return source_map


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env_file(Path(".env"))
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(sqlite_path)
    init_enrichment_table(conn)
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
        keywords = json.loads(keywords_json) if keywords_json else []
        if not isinstance(keywords, list):
            keywords = []
        keywords = [str(k).strip() for k in keywords if isinstance(k, str) and str(k).strip()]
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

    conn.commit()
    conn.close()
    print(f"Enrichment rows written: {rows_written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
