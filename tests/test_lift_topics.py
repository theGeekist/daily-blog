import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestLiftTopics(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"
        self.config = Path.cwd() / "config" / "rules-engine.json"

        conn = sqlite3.connect(self.db)
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
        conn.executemany(
            """
            INSERT INTO claims (
                claim_id, entry_id, headline, who_cares, problem_pressure,
                proposed_solution, evidence_type, sources_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "c1",
                    "e1",
                    "How to improve build reliability",
                    "web engineers",
                    "Builds are slow and flaky",
                    "Apply the described workflow",
                    "anecdote",
                    '["https://example.com/a"]',
                    "2026-02-17T08:05:00+00:00",
                ),
                (
                    "c2",
                    "e2",
                    "LLM model release notes",
                    "ml practitioners",
                    "New model released",
                    "Investigate the claim",
                    "data",
                    '["https://example.com/b"]',
                    "2026-02-17T07:05:00+00:00",
                ),
            ],
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lift_topics_stability(self) -> None:
        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "RULES_ENGINE_CONFIG": str(self.config),
        }
        proc = subprocess.run(
            ["python3", "lift_topics.py"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        conn = sqlite3.connect(self.db)
        topic_rows = conn.execute("SELECT * FROM topic_clusters").fetchall()
        map_rows = conn.execute("SELECT * FROM claim_topic_map").fetchall()
        conn.close()

        self.assertGreaterEqual(len(topic_rows), 1)
        self.assertEqual(len(map_rows), 2)

        # Check topic stability (deterministic IDs on fixed dataset)
        # In current implementation, topic_id is the slug.
        # Let's verify that the same input produces the same topics.
        topics_before = sorted([r[0] for r in topic_rows])

        # Run again
        proc = subprocess.run(
            ["python3", "lift_topics.py"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)

        conn = sqlite3.connect(self.db)
        topic_rows_after = conn.execute("SELECT * FROM topic_clusters").fetchall()
        conn.close()
        topics_after = sorted([r[0] for r in topic_rows_after])

        self.assertEqual(topics_before, topics_after)

if __name__ == "__main__":
    unittest.main()
