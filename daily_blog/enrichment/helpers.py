import json
import urllib.parse


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


def parse_keywords_json(raw: str) -> list[str]:
    loaded = json.loads(raw) if raw else []
    if not isinstance(loaded, list):
        return []
    return [str(k).strip() for k in loaded if isinstance(k, str) and str(k).strip()]


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
