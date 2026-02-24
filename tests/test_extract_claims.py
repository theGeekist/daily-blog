import json
import os
import sqlite3
import subprocess
import unittest
from pathlib import Path

from tests.fixtures import TestBase, make_test_db


class TestExtractClaims(TestBase):
    def setUp(self) -> None:
        super().setUp()
        conn = make_test_db(self.db, ["mentions"])
        conn.executemany(
            """
            INSERT INTO mentions (
                entry_id, source, feed_url, title, url, published, summary, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "e1",
                    "reddit.com",
                    "https://www.reddit.com/r/programming/hot.rss",
                    "How to improve build reliability",
                    "https://example.com/a",
                    "2026-02-17T08:00:00+00:00",
                    "A practical guide with workflow steps",
                    "2026-02-17T08:05:00+00:00",
                ),
                (
                    "e2",
                    "reddit.com",
                    "https://www.reddit.com/r/MachineLearning/new.rss",
                    "LLM model release notes",
                    "https://example.com/b",
                    "2026-02-17T07:00:00+00:00",
                    "Research update and benchmark results",
                    "2026-02-17T07:05:00+00:00",
                ),
            ],
        )
        conn.commit()
        conn.close()

    def test_extract_claims_schema_validation(self) -> None:
        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "MODEL_ROUTING_CONFIG": str(
                Path(__file__).resolve().parent / "model-routing-fast-fail.json"
            ),
            "GOOGLE_API_KEY": "",
        }
        proc = subprocess.run(
            ["python3", "extract_claims.py"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        conn = sqlite3.connect(self.db)
        rows = conn.execute("SELECT * FROM claims").fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        for row in rows:
            # claim_id, entry_id, headline, who_cares, problem_pressure,
            # proposed_solution, evidence_type, sources_json, model_route_used, created_at
            self.assertEqual(len(row), 10)
            self.assertTrue(row[0])  # claim_id
            self.assertTrue(row[2])  # headline
            self.assertTrue(row[3])  # who_cares
            self.assertTrue(row[4])  # problem_pressure
            self.assertTrue(row[5])  # proposed_solution
            self.assertIn(row[6], ["data", "link", "anecdote"])  # evidence_type

            # Validate sources_json is valid JSON
            sources = json.loads(row[7])
            self.assertIsInstance(sources, list)
            self.assertGreater(len(sources), 0)

            self.assertIsInstance(row[8], str)
            self.assertTrue(row[8])


if __name__ == "__main__":
    unittest.main()
