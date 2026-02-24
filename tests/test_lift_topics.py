import os
import sqlite3
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import TestBase, make_test_db


class TestLiftTopics(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self.config = Path.cwd() / "config" / "rules-engine.json"

        conn = make_test_db(self.db, ["claims"])
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

    def test_lift_topics_stability(self) -> None:
        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "RULES_ENGINE_CONFIG": str(self.config),
            "MODEL_ROUTING_CONFIG": str(Path.cwd() / "tests" / "model-routing-fast-fail.json"),
            "GOOGLE_API_KEY": "",
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


class TestAssignTopicsWithModel(unittest.TestCase):
    TOPICS = {
        "ai": ["llm", "model"],
        "engineering": ["dev", "bug"],
        "business": ["startup", "market"],
    }
    BATCH = [
        ("id-1", "LLM inference cost", "too expensive", "use cheaper model"),
        ("id-2", "Rust vs C++ safety", "memory bugs", "use rust"),
        ("id-3", "SaaS churn analysis", "high churn", "improve onboarding"),
    ]

    def _fake_model(self, assignments: list[dict]) -> dict:
        return {"content": {"assignments": assignments}, "model_used": "ollama:llama3.2:latest"}

    def test_schema_omits_claim_id_enum(self) -> None:
        from lift_topics import build_assignment_schema

        schema = build_assignment_schema(topic_slugs=["ai", "engineering", "misc"])
        item_props = schema["properties"]["assignments"]["items"]["properties"]
        self.assertNotIn("enum", item_props["claim_id"])
        self.assertIn("enum", item_props["topic_slug"])

    def test_all_assigned_returns_model_route(self) -> None:
        from lift_topics import assign_topics_with_model

        response = self._fake_model(
            [
                {"claim_id": "id-1", "topic_slug": "ai"},
                {"claim_id": "id-2", "topic_slug": "engineering"},
                {"claim_id": "id-3", "topic_slug": "business"},
            ]
        )
        with patch("lift_topics.call_model", return_value=response):
            result, route = assign_topics_with_model(self.BATCH, self.TOPICS)
        self.assertEqual(result, {"id-1": "ai", "id-2": "engineering", "id-3": "business"})
        self.assertNotIn("partial-heuristic", route)

    def test_partial_response_fills_missing_with_heuristic(self) -> None:
        from lift_topics import assign_topics_with_model

        # Model only assigns id-1 and id-2; id-3 is missing
        response = self._fake_model(
            [
                {"claim_id": "id-1", "topic_slug": "ai"},
                {"claim_id": "id-2", "topic_slug": "engineering"},
            ]
        )
        with patch("lift_topics.call_model", return_value=response):
            result, route = assign_topics_with_model(self.BATCH, self.TOPICS)
        self.assertIn("id-3", result)  # filled by heuristic
        self.assertIn("partial-heuristic", route)

    def test_hallucinated_claim_id_is_skipped(self) -> None:
        from lift_topics import assign_topics_with_model

        # Model returns id-1 correctly but also hallucinates "fake-id"
        response = self._fake_model(
            [
                {"claim_id": "id-1", "topic_slug": "ai"},
                {"claim_id": "fake-id", "topic_slug": "engineering"},  # hallucinated
            ]
        )
        with patch("lift_topics.call_model", return_value=response):
            result, route = assign_topics_with_model(self.BATCH, self.TOPICS)
        self.assertNotIn("fake-id", result)
        self.assertIn("id-2", result)  # filled by heuristic
        self.assertIn("id-3", result)  # filled by heuristic
        self.assertIn("partial-heuristic", route)

    def test_duplicate_assignments_keep_first(self) -> None:
        from lift_topics import assign_topics_with_model

        response = self._fake_model(
            [
                {"claim_id": "id-1", "topic_slug": "ai"},
                {"claim_id": "id-1", "topic_slug": "engineering"},  # duplicate
                {"claim_id": "id-2", "topic_slug": "engineering"},
                {"claim_id": "id-3", "topic_slug": "business"},
            ]
        )
        with patch("lift_topics.call_model", return_value=response):
            result, route = assign_topics_with_model(self.BATCH, self.TOPICS)
        self.assertEqual(result["id-1"], "ai")  # first assignment kept


if __name__ == "__main__":
    unittest.main()
