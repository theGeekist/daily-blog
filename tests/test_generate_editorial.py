import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestGenerateEditorial(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"
        self.outlines = self.root / "top_outlines.md"
        self.research = self.root / "research_pack.json"
        self.routing = Path.cwd() / "config" / "model-routing.json"

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
            INSERT INTO enrichment_sources (
                topic_id, query_terms_json, domain, url, stance,
                credibility_guess, fetched_ok, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ai",
                '["llm"]',
                "example.com",
                "https://example.com/b",
                "neutral",
                "low",
                1,
                "2026-02-17T08:05:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_generate_editorial_output_structure(self) -> None:
        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "TOP_OUTLINES_PATH": str(self.outlines),
            "RESEARCH_PACK_PATH": str(self.research),
            "MODEL_ROUTING_CONFIG": str(self.routing),
        }
        proc = subprocess.run(
            ["python3", "generate_editorial.py"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        self.assertTrue(self.outlines.exists())
        self.assertTrue(self.research.exists())

        # Check markdown structure
        text = self.outlines.read_text(encoding="utf-8")
        self.assertIn("# Top Outlines", text)
        self.assertIn("## Artificial Intelligence", text)
        self.assertIn("topic_id: ai", text)
        self.assertIn("```markdown", text)

        # Check JSON structure
        with self.research.open(encoding="utf-8") as f:
            data = json.load(f)

        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["topic_id"], "ai")
        self.assertGreaterEqual(len(data[0]["sources"]), 1)
        self.assertGreaterEqual(len(data[0]["checklist"]), 1)

        conn = sqlite3.connect(self.db)
        row = conn.execute(
            """
            SELECT outline_markdown, angle, audience, model_route_used
            FROM editorial_candidates
            WHERE topic_id = ?
            """,
            ("ai",),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        outline_markdown, angle, audience, model_route_used = row
        heading_count = len(
            {
                line.strip().lower()
                for line in outline_markdown.splitlines()
                if line.strip().startswith("## ") or line.strip().startswith("### ")
            }
        )
        self.assertGreaterEqual(heading_count, 3)
        self.assertTrue(angle.strip())
        self.assertTrue(audience.strip())
        self.assertTrue(model_route_used.strip())


if __name__ == "__main__":
    unittest.main()
