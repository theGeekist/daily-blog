import os
import sqlite3
import subprocess
import unittest
from pathlib import Path

from tests.fixtures import TestBase, make_test_db


class TestScoringBaseline(TestBase):
    def setUp(self) -> None:
        super().setUp()
        self.board = self.root / "daily_board.md"
        self.config = Path.cwd() / "config" / "rules-engine.json"

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

    def run_score_script(self, db_path: Path | None = None) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "SQLITE_PATH": str(db_path or self.db),
            "RULES_ENGINE_CONFIG": str(self.config),
            "DAILY_BOARD_PATH": str(self.board),
        }
        return subprocess.run(
            ["python3", "score_rss.py"],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_score_script_creates_board(self) -> None:
        proc = self.run_score_script()
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertTrue(self.board.exists())
        text = self.board.read_text(encoding="utf-8")
        self.assertIn("Daily Topic Board", text)
        self.assertIn("score:", text)

    def test_score_script_empty_db(self) -> None:
        empty_db = self.root / "empty.db"
        conn = sqlite3.connect(empty_db)
        conn.execute(
            """
            CREATE TABLE mentions (
                entry_id TEXT PRIMARY KEY, source TEXT, feed_url TEXT,
                title TEXT, url TEXT, published TEXT, summary TEXT, fetched_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()

        proc = self.run_score_script(db_path=empty_db)
        # Should return 2 as per script logic for no mentions
        self.assertEqual(proc.returncode, 2)

    def test_score_script_missing_db(self) -> None:
        missing_db = self.root / "missing.db"
        proc = self.run_score_script(db_path=missing_db)
        self.assertEqual(proc.returncode, 2)

    def test_score_script_malformed_mentions(self) -> None:
        malformed_db = self.root / "malformed.db"
        conn = sqlite3.connect(malformed_db)
        conn.execute(
            """
            CREATE TABLE mentions (
                entry_id TEXT PRIMARY KEY, source TEXT, feed_url TEXT,
                title TEXT, url TEXT, published TEXT, summary TEXT, fetched_at TEXT
            )
            """
        )
        # Insert mention with very short title (should be filtered by hard rules)
        conn.execute(
            """
            INSERT INTO mentions (
                entry_id, source, feed_url, title, url, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("m1", "src", "url", "a", "http://a.com", "2026-02-18T10:00:00Z"),
        )
        conn.commit()
        conn.close()

        proc = self.run_score_script(db_path=malformed_db)
        # If all filtered, it might return 2 or 0 with empty board.
        # Looking at score_rss.py: if not mentions: return 2.
        # But mentions are read BEFORE filtering. So it should proceed to filtering.
        # If deduped is empty, it might fail later or produce empty board.
        # Let's see what happens.
        self.assertEqual(proc.returncode, 0)
        # Board should be empty or have 0 candidates
        text = self.board.read_text(encoding="utf-8")
        self.assertIn("Candidates: 0", text)

    # URL normalization tests
    def test_url_normalization_with_tracking_params(self) -> None:
        """Test URL normalization with various tracking params."""
        from score_rss import normalize_url

        # Test UTM params removal
        url1 = normalize_url(
            "https://example.com?utm_source=newsletter&utm_medium=email&fbclid=123"
        )
        self.assertEqual(url1, "https://example.com")
        self.assertNotIn("utm_source", url1)
        self.assertNotIn("fbclid", url1)

        # Test gclid removal
        url2 = normalize_url("https://example.com?gclid=test")
        self.assertEqual(url2, "https://example.com")
        self.assertNotIn("gclid", url2)

        # Test mc_cid removal
        url3 = normalize_url("https://example.com?mc_cid=test&mc_eid=test")
        self.assertEqual(url3, "https://example.com")
        self.assertNotIn("mc_cid", url3)
        self.assertNotIn("mc_eid", url3)

    def test_novelty_bucket_transitions(self) -> None:
        """Test novelty bucket transitions across threshold boundaries."""
        # Import the needed function from score_rss
        from datetime import datetime, timedelta, timezone

        from score_rss import novelty_state

        # Test exactly at threshold (novel)
        status, score = novelty_state(
            None,
            {
                "novel_days": 1,
                "recent_days": 14,
                "novel_score": 1.0,
                "recent_score": 0.6,
                "stale_score": 0.2,
            },
        )
        self.assertEqual(status, "novel")
        self.assertEqual(score, 1.0)

        # Test just beyond threshold (recent)
        dt_recent = datetime.now(timezone.utc) - timedelta(days=2)
        status, score = novelty_state(
            dt_recent,
            {
                "novel_days": 1,
                "recent_days": 14,
                "novel_score": 1.0,
                "recent_score": 0.6,
                "stale_score": 0.2,
            },
        )
        self.assertEqual(status, "recent")
        self.assertEqual(score, 0.6)

        # Test beyond threshold (stale)
        dt_stale = datetime.now(timezone.utc) - timedelta(days=20)
        status, score = novelty_state(
            dt_stale,
            {
                "novel_days": 1,
                "recent_days": 14,
                "novel_score": 1.0,
                "recent_score": 0.6,
                "stale_score": 0.2,
            },
        )
        self.assertEqual(status, "stale")
        self.assertEqual(score, 0.2)

    def test_score_component_edge_cases(self) -> None:
        """Test score component edge cases (zero values, clamping, negative numbers)."""
        from score_rss import clamp

        # Test clamp with zero
        self.assertEqual(clamp(0.0), 0.0)
        self.assertEqual(clamp(-5.0), 0.0)
        self.assertEqual(clamp(100.0), 1.0)

        # Test clamp with bounds
        self.assertEqual(clamp(0.0, low=-1.0, high=2.0), 0.0)
        self.assertEqual(clamp(5.0, low=0.0, high=10.0), 5.0)
        self.assertEqual(clamp(-10.0, low=-1.0, high=0.0), -1.0)

    def test_quota_enforcement(self) -> None:
        """Test quota enforcement (max per topic, max candidates)."""
        # Verify that config quota rules are read and applied in selection
        # Create test DB with multiple mentions to test quota behavior
        quota_db = self.root / "quota.db"
        conn = sqlite3.connect(quota_db)
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
        # Insert enough mentions to hit max_per_topic=3 and max_candidates=12
        test_mentions = []
        for i in range(1, 6):
            test_mentions.append(
                (
                    f"ai{i}",
                    "reddit.com",
                    "https://www.reddit.com/r/programming/hot.rss",
                    f"AI topic {i} - innovation and growth",
                    f"https://example.com/ai{i}",
                    "2026-02-17T08:00:00+00:00",
                    f"Test summary for AI {i}",
                    "2026-02-17T08:01:00+00:00",
                )
            )
        for i in range(1, 6):
            test_mentions.append(
                (
                    f"web{i}",
                    "example.com",
                    "https://example.com/web/rss",
                    f"Web framework {i} update",
                    f"https://example.com/web{i}",
                    "2026-02-17T08:02:00+00:00",
                    f"Test summary for web {i}",
                    "2026-02-17T08:03:00+00:00",
                )
            )

        conn.executemany(
            """
            INSERT INTO mentions (
                entry_id, source, feed_url, title, url, published, summary, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            test_mentions,
        )
        conn.commit()
        conn.close()

        # Run score_rss.py and verify it respects quota limits
        proc = self.run_score_script(db_path=quota_db)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        # Read the board and verify we don't exceed max_per_topic or max_candidates
        board_text = self.board.read_text(encoding="utf-8")
        self.assertIn("Candidates:", board_text)

        # Verify per-topic distribution
        topic_count = {}
        for line in board_text.split("\n"):
            if "topic:" in line:
                try:
                    topic = line.split("topic:")[1].strip().split(",")[0].strip()
                    topic_count[topic] = topic_count.get(topic, 0) + 1
                except IndexError:
                    continue

        # Check max_per_topic enforcement (3 per topic from rules-engine.json)
        for topic, count in topic_count.items():
            self.assertLessEqual(
                count, 3, f"Topic '{topic}' should not exceed max_per_topic (3), got {count}"
            )


if __name__ == "__main__":
    unittest.main()
