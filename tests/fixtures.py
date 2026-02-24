"""Shared test infrastructure: DDL constants, DB factory, and base test case."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

MENTIONS_DDL = """
CREATE TABLE mentions (
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
CREATE TABLE claims (
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
CREATE TABLE topic_clusters (
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
CREATE TABLE claim_topic_map (
    claim_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    model_route_used TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (claim_id, topic_id)
)
"""

ENRICHMENT_SOURCES_DDL = """
CREATE TABLE enrichment_sources (
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

_DDL_MAP: dict[str, str] = {
    "mentions": MENTIONS_DDL,
    "claims": CLAIMS_DDL,
    "topic_clusters": TOPIC_CLUSTERS_DDL,
    "claim_topic_map": CLAIM_TOPIC_MAP_DDL,
    "enrichment_sources": ENRICHMENT_SOURCES_DDL,
}


def make_test_db(db_path: Path, tables: list[str]) -> sqlite3.Connection:
    """Create a SQLite DB at db_path with the requested tables.

    Returns an open connection so the caller can insert seed data,
    then commit and close it.
    """
    conn = sqlite3.connect(db_path)
    for table in tables:
        conn.execute(_DDL_MAP[table])
    conn.commit()
    return conn


class TestBase(unittest.TestCase):
    """Mixin providing a per-test TemporaryDirectory and a standard db path."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()
