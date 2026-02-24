import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from tests.create_fixture_db import create_fixture_db
except ModuleNotFoundError:  # Allows direct execution: python tests/test_e2e_deterministic.py
    from create_fixture_db import create_fixture_db


class TestE2EDeterministic(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "fixture.db"
        create_fixture_db(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_stage(self, script_name: str) -> None:
        env = {
            **os.environ,
            "SQLITE_PATH": str(self.db),
            "SCORE_BOARD_PATH": str(self.root / "daily_board.md"),
            "EDITORIAL_OUTLINES_PATH": str(self.root / "top_outlines.md"),
            "EDITORIAL_RESEARCH_PACK_PATH": str(self.root / "research_pack.json"),
            "MODEL_ROUTING_CONFIG": str(
                Path(__file__).resolve().parent / "model-routing-fast-fail.json"
            ),
            "ENRICH_SKIP_MODEL": "1",
            "ENRICH_SEARCH_BACKEND": "searxng",
            "SEARXNG_BASE_URL": "http://127.0.0.1:1",
            "EDITORIAL_STATIC_ONLY": "1",
            "GOOGLE_API_KEY": "",
        }
        proc = subprocess.run(
            [sys.executable, script_name],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

    def _run_pipeline_subset(self) -> str:
        self._run_stage("score_rss.py")
        self._run_stage("extract_claims.py")
        self._run_stage("lift_topics.py")
        self._run_stage("enrich_topics.py")
        self._run_stage("generate_editorial.py")
        conn = sqlite3.connect(self.db)
        run_id = conn.execute("SELECT MAX(run_id) FROM candidate_scores").fetchone()[0]
        rows = conn.execute(
            """
            SELECT entry_id
            FROM candidate_scores
            WHERE run_id = ?
            ORDER BY rank_index ASC
            LIMIT 5
            """,
            (run_id,),
        ).fetchall()
        conn.close()
        return "|".join(str(r[0]) for r in rows)

    def test_fixed_fixture_is_deterministic(self) -> None:
        first = self._run_pipeline_subset()
        time.sleep(1.1)
        second = self._run_pipeline_subset()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
