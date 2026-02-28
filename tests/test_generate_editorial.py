import json
import os
import sqlite3
import subprocess
import unittest
from pathlib import Path

from daily_blog.editorial.prompt import build_editorial_prompt
from tests.fixtures import TestBase, make_test_db


class TestGenerateEditorial(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self.outlines = self.root / "top_outlines.md"
        self.research = self.root / "research_pack.json"
        self.routing = Path.cwd() / "config" / "model-routing.json"

        conn = make_test_db(
            self.db, ["topic_clusters", "enrichment_sources", "discussion_receipts"]
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
        conn.execute(
            """
            INSERT INTO discussion_receipts (
                topic_id, source_url, platform, query_used, receipt_text, comment_count,
                problem_statements_json, solution_statements_json, model_route_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ai",
                "https://news.ycombinator.com/item?id=8863",
                "hackernews",
                "dropbox sync thread",
                "users discuss sync issues and alternatives",
                20,
                json.dumps(["Offline workflows still need portable data movement."]),
                json.dumps(["Use rsync-style workflows and verify backup integrity."]),
                "discussion-signals:opencode:openai/gpt-5.2",
                "2026-02-24T08:05:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

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
        self.assertIn("discussion_signals", data[0])
        self.assertGreaterEqual(len(data[0]["discussion_signals"]["problem_statements"]), 1)
        self.assertGreaterEqual(len(data[0]["discussion_signals"]["solution_statements"]), 1)

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

    def test_build_editorial_prompt_includes_discussion_signals(self) -> None:
        prompt = build_editorial_prompt(
            topic_label="Artificial Intelligence",
            why_it_matters="Rapid model quality shifts change decisions.",
            time_horizon="immediate",
            validated_sources=[
                {
                    "domain": "example.com",
                    "credibility_guess": "medium",
                    "url": "https://example.com/report",
                }
            ],
            problem_statements=["Teams cannot validate claims quickly enough."],
            solution_statements=["Adopt verification checkpoints tied to source evidence."],
        )
        self.assertIn("discussion_derived_problems", prompt)
        self.assertIn("discussion_derived_solutions", prompt)
        self.assertIn("Teams cannot validate claims quickly enough.", prompt)
        self.assertIn("Adopt verification checkpoints tied to source evidence.", prompt)


if __name__ == "__main__":
    unittest.main()
