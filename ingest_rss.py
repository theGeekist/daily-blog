#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from daily_blog.config import load_app_config
from daily_blog.core.env import load_env_file
from daily_blog.core.time_utils import now_iso

USER_AGENT = "daily-blog-rss-ingest/0.1 (+local)"


@dataclass
class Mention:
    source: str
    feed_url: str
    entry_id: str
    title: str
    url: str
    published: str
    summary: str
    fetched_at: str


def read_feeds(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Feeds file not found: {path}")

    urls: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def source_from_url(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def text_of(elem: ET.Element | None, tags: list[str]) -> str:
    if elem is None:
        return ""

    for tag in tags:
        found = elem.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def parse_rss_items(
    root: ET.Element, feed_url: str, max_items: int, fetched_at: str
) -> list[Mention]:
    out: list[Mention] = []
    channel = root.find("channel")
    if channel is None:
        return out

    items = channel.findall("item")[:max_items]
    source = source_from_url(feed_url)

    for item in items:
        guid = text_of(item, ["guid"])
        link = text_of(item, ["link"])
        title = text_of(item, ["title"])
        pub = text_of(item, ["pubDate"])
        summary = text_of(item, ["description"])
        entry_id = guid or link or f"{feed_url}:{title}"

        out.append(
            Mention(
                source=source,
                feed_url=feed_url,
                entry_id=entry_id,
                title=title,
                url=link,
                published=pub,
                summary=summary,
                fetched_at=fetched_at,
            )
        )

    return out


def parse_atom_entries(
    root: ET.Element, feed_url: str, max_items: int, fetched_at: str
) -> list[Mention]:
    out: list[Mention] = []
    source = source_from_url(feed_url)
    ns = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(f"{ns}entry")[:max_items]

    for entry in entries:
        entry_id = text_of(entry, [f"{ns}id"])
        title = text_of(entry, [f"{ns}title"])
        published = text_of(entry, [f"{ns}published", f"{ns}updated"])
        summary = text_of(entry, [f"{ns}summary", f"{ns}content"])

        link_elem = entry.find(f"{ns}link")
        link = ""
        if link_elem is not None:
            link = (link_elem.attrib.get("href") or "").strip()

        if not entry_id:
            entry_id = link or f"{feed_url}:{title}"

        out.append(
            Mention(
                source=source,
                feed_url=feed_url,
                entry_id=entry_id,
                title=title,
                url=link,
                published=published,
                summary=summary,
                fetched_at=fetched_at,
            )
        )

    return out


def parse_feed(xml_bytes: bytes, feed_url: str, max_items: int, fetched_at: str) -> list[Mention]:
    root = ET.fromstring(xml_bytes)

    if root.tag == "rss" or root.find("channel") is not None:
        return parse_rss_items(root, feed_url, max_items, fetched_at)

    if root.tag.endswith("feed"):
        return parse_atom_entries(root, feed_url, max_items, fetched_at)

    return []


def fetch_feed(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mentions (
            entry_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            feed_url TEXT NOT NULL,
            title TEXT,
            url TEXT,
            published TEXT,
            summary TEXT,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def write_jsonl(path: Path, mentions: list[Mention]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for mention in mentions:
            f.write(json.dumps(mention.__dict__, ensure_ascii=True) + "\n")


def upsert_mentions(conn: sqlite3.Connection, mentions: list[Mention]) -> int:
    inserted = 0
    for m in mentions:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO mentions (
                entry_id, source, feed_url, title, url, published, summary, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m.entry_id,
                m.source,
                m.feed_url,
                m.title,
                m.url,
                m.published,
                m.summary,
                m.fetched_at,
            ),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def main() -> int:
    load_env_file(Path(".env"))
    project_root = Path(__file__).resolve().parent
    app_cfg = load_app_config(project_root=project_root, environ=os.environ)

    feeds_file = app_cfg.paths.feeds_file
    sqlite_path = app_cfg.paths.sqlite_path
    output_jsonl = app_cfg.paths.output_jsonl
    max_items = app_cfg.ingest.max_items_per_feed

    try:
        feeds = read_feeds(feeds_file)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    if not feeds:
        print(f"No feeds configured in {feeds_file}", file=sys.stderr)
        return 2

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    init_db(conn)

    all_mentions: list[Mention] = []
    failed = 0
    for url in feeds:
        fetched_at = now_iso()
        try:
            payload = fetch_feed(url)
            mentions = parse_feed(payload, url, max_items, fetched_at)
            all_mentions.extend(mentions)
            print(f"OK   {url} -> {len(mentions)} items")
        except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as e:
            failed += 1
            print(f"FAIL {url} -> {e}", file=sys.stderr)

    write_jsonl(output_jsonl, all_mentions)
    inserted = upsert_mentions(conn, all_mentions)
    conn.close()

    print("---")
    print(f"Feeds: {len(feeds)}")
    print(f"Failed feeds: {failed}")
    print(f"Fetched mentions: {len(all_mentions)}")
    print(f"New DB rows: {inserted}")
    print(f"JSONL path: {output_jsonl}")
    print(f"SQLite path: {sqlite_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
