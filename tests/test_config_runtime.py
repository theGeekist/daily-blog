import re
import tempfile
import unittest
from pathlib import Path

from daily_blog.config.runtime import ALL_ENV_KEYS, load_app_config, resolve_stage_timeouts


class TestConfigRuntime(unittest.TestCase):
    def test_env_registry_covers_all_getenv_calls(self) -> None:
        root = Path(__file__).resolve().parent.parent
        python_files = [*root.glob("*.py"), *root.glob("daily_blog/**/*.py")]
        found: set[str] = set()
        pattern = re.compile(r"os\.getenv\(\s*[\"']([A-Z0-9_]+)[\"']")
        for file in python_files:
            content = file.read_text(encoding="utf-8", errors="ignore")
            found.update(pattern.findall(content))

        missing = sorted(found - ALL_ENV_KEYS)
        self.assertEqual(missing, [], msg=f"Missing env keys in ALL_ENV_KEYS: {missing}")

    def test_load_app_config_parses_and_clamps(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        environ = {
            "SQLITE_PATH": "./data/custom.db",
            "PIPELINE_RETRIES": "5",
            "PIPELINE_SKIP_STAGES": '["ingest","score"]',
            "PIPELINE_STAGE_TIMEOUT_SECONDS": "420",
            "PIPELINE_STAGE_TIMEOUTS": '{"enrich_topics":180}',
            "ENRICH_FETCH_TIMEOUT_SECONDS": "15",
            "ENRICH_DISCOVER_LIMIT": "0",
            "ENRICH_MAX_KNOWN_CLAIM_URLS": "100",
            "ENRICH_MAX_TOPICS": "12",
            "EDITORIAL_STATIC_ONLY": "true",
        }
        cfg = load_app_config(project_root=project_root, environ=environ)
        self.assertEqual(str(cfg.paths.sqlite_path), "data/custom.db")
        self.assertEqual(cfg.pipeline.retries, 5)
        self.assertEqual(cfg.pipeline.skip_stages, {"ingest", "score"})
        self.assertEqual(cfg.pipeline.stage_timeout_seconds, 420)
        self.assertEqual(cfg.pipeline.stage_timeouts_override.get("enrich_topics"), 180)
        self.assertEqual(cfg.enrichment.fetch_timeout_seconds, 15)
        self.assertEqual(cfg.enrichment.discover_limit, 0)
        self.assertEqual(cfg.enrichment.max_known_claim_urls, 100)
        self.assertEqual(cfg.enrichment.max_topics, 12)
        self.assertTrue(cfg.editorial.static_only)

    def test_resolve_stage_timeouts_honors_file_and_env_override(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            timeouts_file = Path(tmp) / "timeouts.json"
            timeouts_file.write_text('{"extract_claims": 111}', encoding="utf-8")
            cfg = load_app_config(
                project_root=project_root,
                environ={
                    "PIPELINE_STAGE_TIMEOUT_SECONDS": "300",
                    "PIPELINE_TIMEOUTS_PATH": str(timeouts_file),
                    "PIPELINE_STAGE_TIMEOUTS": '{"extract_claims":222,"enrich_topics":444}',
                },
            )
            result = resolve_stage_timeouts(["extract_claims", "enrich_topics"], cfg)
            self.assertEqual(result["extract_claims"], 222)
            self.assertEqual(result["enrich_topics"], 444)


if __name__ == "__main__":
    unittest.main()
