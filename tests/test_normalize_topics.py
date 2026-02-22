import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestNormalizeTopics(unittest.TestCase):
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
                model_route_used TEXT,
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
                model_route_used TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (claim_id, topic_id)
            )
            """
        )

        conn.execute(
            """
            INSERT INTO topic_clusters (
                topic_id, parent_topic_slug, parent_topic_label,
                why_it_matters, time_horizon, claim_count,
                keywords_json, model_route_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ai",
                "ai",
                "Ai",
                "Model capability changes",
                "evergreen",
                2,
                '["llm"]',
                "topic_lifter:test",
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
                "LLM release cadence accelerates",
                "engineering leaders",
                "Frequent releases cause tooling churn",
                "Adopt a gated evaluation workflow",
                "data",
                '["https://example.com/a"]',
                "2026-02-17T08:05:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO claim_topic_map (claim_id, topic_id, model_route_used, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("c1", "ai", "topic_lifter:test", "2026-02-17T08:05:00+00:00"),
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_normalize_topics_outputs_curated_labels(self) -> None:
        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "MODEL_ROUTING_CONFIG": str(Path.cwd() / "tests" / "model-routing-fast-fail.json"),
            "GOOGLE_API_KEY": "",
        }
        proc = subprocess.run(
            ["python3", "normalize_topics.py"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        conn = sqlite3.connect(self.db)
        row = conn.execute(
            """
            SELECT normalized_topic_slug, normalized_topic_label, curator_model_route_used
            FROM topic_clusters
            WHERE topic_id = ?
            """,
            ("ai",),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        normalized_slug, normalized_label, route_used = row
        self.assertTrue(normalized_slug)
        self.assertTrue(normalized_label)
        self.assertEqual(normalized_slug, "ai")
        self.assertEqual(normalized_label, "AI")
        self.assertTrue(route_used)


if __name__ == "__main__":
    unittest.main()
