import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import orchestrator_utils


class TestOrchestratorUtils(unittest.TestCase):
    def test_candidate_models_supports_fallback_chain(self) -> None:
        models = orchestrator_utils._candidate_models(
            {
                "primary": "opencode:openai/gpt-5.2",
                "fallback": "opencode:openai/gpt-5.2-codex",
                "fallbacks": [
                    "ollama:llama3.2:latest",
                    "ollama:llama3.1:8b",
                    "opencode:openai/gpt-5.2",
                ],
            }
        )
        self.assertEqual(
            models,
            [
                "opencode:openai/gpt-5.2",
                "opencode:openai/gpt-5.2-codex",
                "ollama:llama3.2:latest",
                "ollama:llama3.1:8b",
            ],
        )

    def test_call_model_tries_fallbacks_after_primary_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routing_path = Path(tmp) / "routing.json"
            routing_path.write_text(
                json.dumps(
                    {
                        "enrichment": {
                            "primary": "opencode:primary",
                            "fallback": "opencode:fallback",
                            "fallbacks": ["opencode:backup-1", "opencode:backup-2"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                orchestrator_utils, "DEFAULT_MODEL_ROUTING_PATH", routing_path
            ), patch.object(
                orchestrator_utils,
                "_run_model_cli",
                side_effect=[
                    orchestrator_utils.ModelCallError("primary failed"),
                    orchestrator_utils.ModelCallError("fallback failed"),
                    '{"ok": true}',
                ],
            ) as run_cli:
                result = orchestrator_utils.call_model("enrichment", "prompt", schema=None)

            self.assertEqual(result["model_used"], "opencode:backup-1")
            self.assertEqual(result["content"], {"ok": True})
            called_models = [call.kwargs["model_name"] for call in run_cli.call_args_list]
            self.assertEqual(
                called_models,
                ["opencode:primary", "opencode:fallback", "opencode:backup-1"],
            )


if __name__ == "__main__":
    unittest.main()
