import unittest
from unittest.mock import patch

from orchestrator_utils import ModelCallError, ModelOutputValidationError, _invoke_with_retries


class TestOrchestratorUtils(unittest.TestCase):
    def test_no_retry_for_hard_failure(self) -> None:
        with patch(
            "orchestrator_utils._dispatch_model",
            side_effect=ModelCallError("missing key"),
        ) as dispatch:
            with self.assertRaises(ModelCallError):
                _invoke_with_retries(
                    model_name="gemini:gemini-2.0-flash",
                    prompt="x",
                    schema={"type": "object"},
                    retries=2,
                )
        self.assertEqual(dispatch.call_count, 1)

    def test_retry_for_output_validation_failure(self) -> None:
        responses = ["not json", '{"ok": true}']

        def _fake_dispatch(model_name: str, prompt: str, schema: dict | None) -> str:
            del model_name, prompt, schema
            return responses.pop(0)

        with patch("orchestrator_utils._dispatch_model", side_effect=_fake_dispatch) as dispatch:
            parsed = _invoke_with_retries(
                model_name="opencode:test",
                prompt="x",
                schema={
                    "type": "object",
                    "required": ["ok"],
                    "properties": {"ok": {"type": "boolean"}},
                },
                retries=2,
            )

        self.assertEqual(parsed, {"ok": True})
        self.assertEqual(dispatch.call_count, 2)

    def test_exhausted_retry_raises_validation_error(self) -> None:
        with patch("orchestrator_utils._dispatch_model", return_value="not json"):
            with self.assertRaises(ModelOutputValidationError):
                _invoke_with_retries(
                    model_name="opencode:test",
                    prompt="x",
                    schema={"type": "object"},
                    retries=1,
                )


if __name__ == "__main__":
    unittest.main()
