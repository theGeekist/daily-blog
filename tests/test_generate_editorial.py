import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
            "MODEL_ROUTING_CONFIG": str(Path.cwd() / "tests" / "model-routing-fast-fail.json"),
            "GOOGLE_API_KEY": "",
            "EDITORIAL_STATIC_ONLY": "1",
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

    def test_generate_editorial_model_path_and_persisted_evidence_brief(self) -> None:
        import generate_editorial

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
                "Adopt a staged rollout",
                "data",
                "[]",
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
        conn.execute(
            "DELETE FROM enrichment_sources WHERE topic_id = ?",
            ("ai",),
        )
        for idx, domain in enumerate(("nasa.gov", "nih.gov", "nist.gov"), start=1):
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
                    domain,
                    f"https://{domain}/report-{idx}",
                    "supports",
                    "high",
                    1,
                    "2026-02-17T08:05:00+00:00",
                ),
            )
        conn.commit()
        conn.close()

        def fake_call_model(stage_name: str, prompt: str, schema: dict | None = None) -> dict:
            del prompt, schema
            if stage_name == "evidence_synthesis":
                return {
                    "model_used": "gemini:gemini-2.0-flash",
                    "content": {
                        "topic_id": "ai",
                        "claim_count": 1,
                        "top_claims": ["LLM model release notes"],
                        "problem_pressures": ["New model released"],
                        "proposed_solutions": ["Adopt a staged rollout"],
                        "evidence_type_counts": {"data": 1},
                        "stance_breakdown": {"supports": 3},
                        "dominant_pattern": "data-backed",
                        "outline_strategy": "implementation-guide",
                    },
                }
            return {
                "model_used": "gemini:gemini-2.0-flash",
                "content": {
                    "title_options": [
                        "AI rollout playbook",
                        "Staged adoption guide",
                        "AI risk controls",
                    ],
                    "outline_markdown": (
                        "## What Changed\n- New capabilities\n\n"
                        "## Step-by-Step\n1. Baseline\n2. Rollout\n\n"
                        "## Conclusion\n- Next action"
                    ),
                    "narrative_draft_markdown": (
                        "## Intro hook\n- Why now\n\n## Storyline\n- Setup\n\n"
                        "## Sections\n1. Action\n\n## Outro\n- Verify"
                    ),
                    "talking_points": ["Rollout gates", "Risk controls"],
                    "verification_checklist": [
                        "Validate source recency",
                        "Confirm domain diversity",
                    ],
                    "angle": "Execution-focused analysis.",
                    "audience": "Operators",
                },
            }

        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "TOP_OUTLINES_PATH": str(self.outlines),
            "RESEARCH_PACK_PATH": str(self.research),
            "MODEL_ROUTING_CONFIG": str(self.routing),
            "EDITORIAL_STATIC_ONLY": "0",
            "GOOGLE_API_KEY": "",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch(
                "generate_editorial.call_model",
                side_effect=fake_call_model,
            ),
            patch(
                "daily_blog.editorial.synthesis.call_model",
                side_effect=fake_call_model,
            ),
        ):
            rc = generate_editorial.main()
        self.assertEqual(rc, 0)

        conn = sqlite3.connect(self.db)
        row = conn.execute(
            """
            SELECT model_route_used, evidence_brief_json
            FROM editorial_candidates
            WHERE topic_id = ?
            """,
            ("ai",),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        model_route_used, evidence_brief_json = row
        self.assertEqual(model_route_used, "gemini:gemini-2.0-flash")
        brief = json.loads(evidence_brief_json)
        self.assertEqual(brief["outline_strategy"], "implementation-guide")

    def test_misc_topic_skipped_by_default(self) -> None:
        import generate_editorial

        conn = sqlite3.connect(self.db)
        conn.execute(
            """
            INSERT INTO topic_clusters (
                topic_id, parent_topic_slug, parent_topic_label, why_it_matters,
                time_horizon, claim_count, keywords_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "misc",
                "misc",
                "General Engineering",
                "Uncategorised catch-all",
                "evergreen",
                5,
                "[]",
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
                "misc",
                "[]",
                "reddit.com",
                "https://reddit.com/r/misc/1",
                "neutral",
                "medium",
                1,
                "2026-02-17T08:05:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

        base_env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "TOP_OUTLINES_PATH": str(self.outlines),
            "RESEARCH_PACK_PATH": str(self.research),
            "MODEL_ROUTING_CONFIG": str(Path.cwd() / "tests" / "model-routing-fast-fail.json"),
            "EDITORIAL_STATIC_ONLY": "1",
            "GOOGLE_API_KEY": "",
        }

        # Default: EDITORIAL_INCLUDE_MISC not set → misc skipped
        with patch.dict(os.environ, {**base_env, "EDITORIAL_INCLUDE_MISC": "0"}, clear=False):
            rc = generate_editorial.main()
        self.assertEqual(rc, 0)

        conn = sqlite3.connect(self.db)
        slugs = {
            row[0] for row in conn.execute("SELECT topic_id FROM editorial_candidates").fetchall()
        }
        conn.close()
        self.assertNotIn("misc", slugs)
        self.assertIn("ai", slugs)

        # Opt-in: EDITORIAL_INCLUDE_MISC=1 → misc included
        with patch.dict(os.environ, {**base_env, "EDITORIAL_INCLUDE_MISC": "1"}, clear=False):
            rc = generate_editorial.main()
        self.assertEqual(rc, 0)

        conn = sqlite3.connect(self.db)
        slugs = {
            row[0] for row in conn.execute("SELECT topic_id FROM editorial_candidates").fetchall()
        }
        conn.close()
        self.assertIn("misc", slugs)


if __name__ == "__main__":
    unittest.main()
