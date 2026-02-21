import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestPipelineStages(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"
        conn = sqlite3.connect(self.db)
        conn.execute(
            """
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
        )
        conn.executemany(
            """
            INSERT INTO mentions (
                entry_id, source, feed_url, title, url, published, summary, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "a1",
                    "reddit.com",
                    "https://www.reddit.com/r/programming/hot.rss",
                    "How to debug distributed systems in production",
                    "https://example.com/guide",
                    "2026-02-17T08:00:00+00:00",
                    "A checklist and workflow for debugging",
                    "2026-02-17T08:01:00+00:00",
                ),
                (
                    "a2",
                    "reddit.com",
                    "https://www.reddit.com/r/MachineLearning/new.rss",
                    "LLM benchmark study on inference efficiency",
                    "https://arxiv.org/abs/2602.12345",
                    "2026-02-17T07:00:00+00:00",
                    "Research paper with benchmark data",
                    "2026-02-17T07:01:00+00:00",
                ),
            ],
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, script: str) -> None:
        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "RULES_ENGINE_CONFIG": str(Path.cwd() / "config" / "rules-engine.json"),
            "TOP_OUTLINES_PATH": str(self.root / "top_outlines.md"),
            "RESEARCH_PACK_PATH": str(self.root / "research_pack.json"),
            "MODEL_ROUTING_CONFIG": str(Path.cwd() / "config" / "model-routing.json"),
        }
        proc = subprocess.run(["python3", script], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

    def test_extract_to_editorial_path(self) -> None:
        self.run_script("extract_claims.py")
        self.run_script("lift_topics.py")
        self.run_script("enrich_topics.py")
        self.run_script("generate_editorial.py")

        conn = sqlite3.connect(self.db)
        claim_count = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        topic_count = conn.execute("SELECT COUNT(*) FROM topic_clusters").fetchone()[0]
        enrich_count = conn.execute("SELECT COUNT(*) FROM enrichment_sources").fetchone()[0]
        editorial_count = conn.execute("SELECT COUNT(*) FROM editorial_candidates").fetchone()[0]
        conn.close()

        self.assertGreaterEqual(claim_count, 2)
        self.assertGreaterEqual(topic_count, 1)
        self.assertGreaterEqual(enrich_count, 1)
        self.assertGreaterEqual(editorial_count, 1)

        self.assertTrue((self.root / "top_outlines.md").exists())
        self.assertTrue((self.root / "research_pack.json").exists())


if __name__ == "__main__":
    unittest.main()
