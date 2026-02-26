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
    if limit <= 0:
        return []
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
    for url in extracted_urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
        if len(deduped) >= limit:
            break
    return deduped
