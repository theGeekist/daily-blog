import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestEnrichTopics(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"

        conn = sqlite3.connect(self.db)
        conn.execute(
            """
            CREATE TABLE topic_clusters (
                topic_id TEXT PRIMARY KEY,
                parent_topic_slug TEXT NOT NULL,
                parent_topic_label TEXT NOT NULL,
                why_it_matters TEXT NOT NULL,
                time_horizon TEXT NOT NULL,
                claim_count INTEGER NOT NULL,
                keywords_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
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
        )
        conn.execute(
            """
            CREATE TABLE claim_topic_map (
                claim_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (claim_id, topic_id)
            )
            """
        )

        conn.execute(
            """
            INSERT INTO topic_clusters (
                topic_id, parent_topic_slug, parent_topic_label, why_it_matters,
                time_horizon, claim_count, keywords_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ai",
                "ai",
                "Artificial Intelligence",
                "Model capability and reliability changes",
                "evergreen",
                1,
                '["llm", "model"]',
                "2026-02-17T08:05:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO claims (
                claim_id, entry_id, headline, who_cares, problem_pressure,
                proposed_solution, evidence_type, sources_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "c1",
                "e1",
                "LLM model release notes",
                "ml practitioners",
                "New model released",
                "Investigate the claim",
                "data",
                '["https://example.com/b"]',
                "2026-02-17T07:05:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO claim_topic_map (claim_id, topic_id, created_at)
            VALUES (?, ?, ?)
            """,
            ("c1", "ai", "2026-02-17T08:05:00+00:00"),
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enrich_topics_citation_validity(self) -> None:
        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
        }
        proc = subprocess.run(
            ["python3", "enrich_topics.py"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        conn = sqlite3.connect(self.db)
        rows = conn.execute("SELECT * FROM enrichment_sources").fetchall()
        conn.close()

        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            # topic_id, query_terms_json, domain, url, stance,
            # credibility_guess, fetched_ok, created_at
            self.assertEqual(len(row), 8)
            self.assertEqual(row[0], "ai")
            self.assertTrue(row[3].startswith("http"))  # url
            self.assertIn(row[5], ["low", "medium", "high"])  # credibility_guess
            self.assertIn(row[6], [0, 1])


if __name__ == "__main__":
    unittest.main()
