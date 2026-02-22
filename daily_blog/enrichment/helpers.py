import json
import urllib.parse


def credibility_for_domain(domain: str, url: str = "") -> str:
    high = {
        # Academic & standards
        "nature.com",
        "science.org",
        "nejm.org",
        "acm.org",
        "ieee.org",
        # Pre-print & primary research
        "arxiv.org",
        # Tech primary sources
        "research.google",
        "ai.meta.com",
        "openai.com",
        "anthropic.com",
        "huggingface.co",
        # Tech journalism (primary reporting)
        "techcrunch.com",
        "arstechnica.com",
        "wired.com",
        "thenextweb.com",
        # Standards & documentation
        "developer.mozilla.org",
        "docs.python.org",
        "nodejs.org",
        # Business primary sources
        "wsj.com",
        "ft.com",
        "bloomberg.com",
        # Open source governance
        "github.blog",
        "about.gitlab.com",
    }
    medium = {
        "github.com",
        "reddit.com",
        "wikipedia.org",
        "stackexchange.com",
    }
    if domain in high:
        return "high"
    if domain.endswith(".edu") or domain.endswith(".gov"):
        return "high"
    # URL-path upgrade: allow documentation/research path hints only on trusted domain classes.
    if url:
        path = urllib.parse.urlparse(url).path.lower()
        path_has_research_hint = any(
            seg in path for seg in ("/papers/", "/research/", "/publications/", "/docs/")
        )
        trusted_for_upgrade = domain in high or domain.endswith((".edu", ".gov", ".org"))
        if path_has_research_hint and trusted_for_upgrade:
            return "high"
    if domain in medium:
        return "medium"
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
    min_domain_diversity: int = 3,
    max_per_domain: int = 3,
) -> dict[str, dict[str, str | int]]:
    high_medium_urls = [
        url
        for url, source in source_map.items()
        if credibility_rank(str(source.get("credibility_guess", "low"))) >= 2
    ]
    candidate_map = (
        {url: source_map[url] for url in high_medium_urls}
        if len(high_medium_urls) >= min_credible_count
        else dict(source_map)
    )

    # Cap dominance from any single domain while preserving original insertion order.
    per_domain_count: dict[str, int] = {}
    capped: dict[str, dict[str, str | int]] = {}
    for url, source in candidate_map.items():
        domain = str(source.get("domain", "")).strip().lower() or domain_for_url(url)
        count = per_domain_count.get(domain, 0)
        if domain and count >= max_per_domain:
            continue
        capped[url] = source
        if domain:
            per_domain_count[domain] = count + 1

    if len(per_domain_count) >= min_domain_diversity:
        return capped

    # Diversity not met; fall back to uncapped set so upstream can decide how to handle scarcity.
    return candidate_map
