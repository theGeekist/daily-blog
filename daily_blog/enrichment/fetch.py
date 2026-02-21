import json
import os
import time
import urllib.parse
import urllib.request

from daily_blog.enrichment.helpers import domain_for_url, normalize_url


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
    backend = os.getenv("ENRICH_SEARCH_BACKEND", "ddgs").strip().lower()
    query = " ".join([topic_label] + query_terms[:6]).strip()
    if not query:
        return []

    if backend == "searxng":
        return _discover_searxng(query=query, limit=limit)
    return _discover_ddgs(query=query, limit=limit)


def _discover_ddgs(query: str, limit: int) -> list[str]:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return []

    extracted_urls: list[str] = []
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=limit)
            for row in results:
                if not isinstance(row, dict):
                    continue
                candidate = normalize_url(str(row.get("href", "")))
                if not candidate:
                    continue
                domain = domain_for_url(candidate)
                if domain.endswith("duckduckgo.com"):
                    continue
                extracted_urls.append(candidate)
    except Exception:
        return []

    return _dedupe_urls(extracted_urls, limit=limit)


def _discover_searxng(query: str, limit: int) -> list[str]:
    base = os.getenv("SEARXNG_BASE_URL", "http://localhost:8888").rstrip("/")
    engines = os.getenv("SEARXNG_ENGINES", "google,bing,duckduckgo,brave")
    user_agent = os.getenv(
        "ENRICH_FETCH_USER_AGENT",
        "Mozilla/5.0 (compatible; daily-blog-enrichment/0.2; +https://localhost)",
    )
    timeout_seconds = int(os.getenv("ENRICH_FETCH_TIMEOUT_SECONDS", "10"))

    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "engines": engines,
            "language": "en-US",
        }
    )
    url = f"{base}/search?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept": "application/json,*/*;q=0.8"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception:
        return []

    results = payload.get("results", []) if isinstance(payload, dict) else []
    urls: list[str] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        candidate = normalize_url(str(row.get("url", "")))
        if candidate:
            urls.append(candidate)
    return _dedupe_urls(urls, limit=limit)


def _dedupe_urls(urls: list[str], limit: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
        if len(deduped) >= limit:
            break
    return deduped
