import json
import os
import urllib.parse
import urllib.request

from daily_blog.enrichment.helpers import normalize_url


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    if value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def _http_get_json(url: str, timeout_seconds: int, user_agent: str) -> object | None:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json,text/plain;q=0.8,*/*;q=0.6",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="ignore")
        return json.loads(payload)
    except Exception:
        return None


def _extract_reddit_post_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    if not (host == "reddit.com" or host.endswith(".reddit.com")):
        return ""
    parts = [p for p in parsed.path.split("/") if p]
    if "comments" not in parts:
        return ""
    idx = parts.index("comments")
    if idx + 1 >= len(parts):
        return ""
    return parts[idx + 1].strip()


def _extract_hn_item_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    if host != "news.ycombinator.com":
        return ""
    query = urllib.parse.parse_qs(parsed.query)
    item_id = (query.get("id") or [""])[0].strip()
    return item_id


def _collect_hn_comments(
    item_ids: list[int],
    timeout_seconds: int,
    user_agent: str,
    max_comments: int,
    depth_limit: int,
) -> list[dict[str, str | int]]:
    comments: list[dict[str, str | int]] = []
    queue: list[tuple[int, int]] = [(item_id, 0) for item_id in item_ids]
    seen: set[int] = set()
    while queue and len(comments) < max_comments:
        item_id, depth = queue.pop(0)
        if item_id in seen or depth > depth_limit:
            continue
        seen.add(item_id)
        payload = _http_get_json(
            f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "comment":
            text = str(payload.get("text", "")).strip()
            if text:
                comments.append(
                    {
                        "id": int(payload.get("id") or item_id),
                        "score": 0,
                        "text": text[:1200],
                    }
                )
        kids = payload.get("kids")
        if isinstance(kids, list) and depth < depth_limit:
            for kid in kids:
                if isinstance(kid, int):
                    queue.append((kid, depth + 1))
    return comments


def _harvest_reddit_discussion(
    url: str,
    timeout_seconds: int,
    user_agent: str,
    max_comments: int,
) -> dict[str, object] | None:
    post_id = _extract_reddit_post_id(url)
    if not post_id:
        return None

    payload = _http_get_json(
        f"https://www.reddit.com/comments/{post_id}.json?limit={max_comments}&depth=2&raw_json=1",
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
    )
    if not isinstance(payload, list) or len(payload) < 2:
        return None

    post_data = {}
    try:
        post_data = payload[0]["data"]["children"][0]["data"]  # type: ignore[index]
    except Exception:
        post_data = {}
    try:
        comments_root = payload[1]["data"]["children"]  # type: ignore[index]
    except Exception:
        comments_root = []

    comments: list[dict[str, str | int]] = []
    for child in comments_root:
        if len(comments) >= max_comments:
            break
        if not isinstance(child, dict):
            continue
        data = child.get("data")
        if not isinstance(data, dict):
            continue
        body = str(data.get("body", "")).strip()
        if not body:
            continue
        comments.append(
            {
                "id": str(data.get("id", "")),
                "score": int(data.get("score", 0) or 0),
                "text": body[:1200],
            }
        )

    if not comments:
        return None
    title = str(post_data.get("title", "")).strip()
    subreddit = str(post_data.get("subreddit", "")).strip()
    return {
        "platform": "reddit",
        "source_url": normalize_url(url),
        "query_used": f"{title} {subreddit}".strip(),
        "receipt_text": "\n".join([str(c["text"]) for c in comments[: min(12, len(comments))]]),
        "comment_count": len(comments),
        "comments_json": json.dumps(comments, ensure_ascii=True),
    }


def _harvest_hn_discussion(
    url: str,
    timeout_seconds: int,
    user_agent: str,
    max_comments: int,
) -> dict[str, object] | None:
    item_id = _extract_hn_item_id(url)
    if not item_id:
        return None

    root = _http_get_json(
        f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
    )
    if not isinstance(root, dict):
        return None

    kids = root.get("kids")
    top_level_ids = [int(k) for k in kids if isinstance(k, int)] if isinstance(kids, list) else []
    comments = _collect_hn_comments(
        item_ids=top_level_ids[:20],
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        max_comments=max_comments,
        depth_limit=2,
    )
    if not comments:
        return None

    title = str(root.get("title", "")).strip()
    return {
        "platform": "hackernews",
        "source_url": normalize_url(url),
        "query_used": title,
        "receipt_text": "\n".join([str(c["text"]) for c in comments[: min(12, len(comments))]]),
        "comment_count": len(comments),
        "comments_json": json.dumps(comments, ensure_ascii=True),
    }


def harvest_discussion_receipts(
    source_urls: list[str],
) -> list[dict[str, object]]:
    timeout_seconds = _env_int("ENRICH_DISCUSSION_TIMEOUT_SECONDS", 12, minimum=1, maximum=120)
    max_threads = _env_int("ENRICH_DISCUSSION_MAX_THREADS", 3, minimum=0, maximum=20)
    max_comments = _env_int("ENRICH_DISCUSSION_MAX_COMMENTS", 20, minimum=0, maximum=200)
    user_agent = os.getenv(
        "ENRICH_FETCH_USER_AGENT",
        "Mozilla/5.0 (compatible; daily-blog-discussion/0.1; +https://localhost)",
    )

    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_url in source_urls:
        normalized = normalize_url(raw_url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if len(out) >= max_threads:
            break

        reddit = _harvest_reddit_discussion(
            url=normalized,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            max_comments=max_comments,
        )
        if reddit is not None:
            out.append(reddit)
            continue

        hn = _harvest_hn_discussion(
            url=normalized,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            max_comments=max_comments,
        )
        if hn is not None:
            out.append(hn)

    return out
