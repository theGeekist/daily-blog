"""Shared test fixtures and base class for daily-blog test suite."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

MENTIONS_DDL = """
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

CLAIMS_DDL = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    headline TEXT NOT NULL,
    who_cares TEXT NOT NULL,
    problem_pressure TEXT NOT NULL,
    proposed_solution TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

TOPIC_CLUSTERS_DDL = """
CREATE TABLE IF NOT EXISTS topic_clusters (
    topic_id TEXT PRIMARY KEY,
    parent_topic_slug TEXT NOT NULL,
    parent_topic_label TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    time_horizon TEXT NOT NULL,
    claim_count INTEGER NOT NULL,
    keywords_json TEXT NOT NULL,
    model_route_used TEXT,
    created_at TEXT NOT NULL
)
"""

CLAIM_TOPIC_MAP_DDL = """
CREATE TABLE IF NOT EXISTS claim_topic_map (
    claim_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    model_route_used TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (claim_id, topic_id)
)
"""

ENRICHMENT_SOURCES_DDL = """
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

DISCUSSION_RECEIPTS_DDL = """
CREATE TABLE IF NOT EXISTS discussion_receipts (
    topic_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    platform TEXT NOT NULL,
    query_used TEXT NOT NULL,
    receipt_text TEXT NOT NULL,
    comment_count INTEGER NOT NULL,
    problem_statements_json TEXT NOT NULL,
    solution_statements_json TEXT NOT NULL,
    model_route_used TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, source_url)
)
"""

_DDL_MAP: dict[str, str] = {
    "mentions": MENTIONS_DDL,
    "claims": CLAIMS_DDL,
    "topic_clusters": TOPIC_CLUSTERS_DDL,
    "claim_topic_map": CLAIM_TOPIC_MAP_DDL,
    "enrichment_sources": ENRICHMENT_SOURCES_DDL,
    "discussion_receipts": DISCUSSION_RECEIPTS_DDL,
}


def make_test_db(db_path: Path, tables: list[str]) -> sqlite3.Connection:
    """Create a SQLite DB at db_path with the requested tables and return the connection."""
    conn = sqlite3.connect(db_path)
    for table in tables:
        ddl = _DDL_MAP[table]
        conn.execute(ddl)
    conn.commit()
    return conn


class TestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()
