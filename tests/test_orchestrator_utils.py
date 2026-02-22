import os
import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

from orchestrator_utils import (
    ModelCallError,
    ModelOutputValidationError,
    _extract_json_payload,
    _invoke_with_retries,
)


def _make_genai_mock() -> tuple[MagicMock, MagicMock, dict[str, ModuleType]]:
    """Return (mock_genai, mock_types, sys_modules_patch) for _dispatch_gemini tests."""
    mock_types = MagicMock()
    mock_genai = MagicMock()
    mock_genai.types = mock_types

    mock_google_pkg = MagicMock()
    mock_google_pkg.genai = mock_genai

    modules: dict[str, ModuleType] = {
        "google": mock_google_pkg,
        "google.genai": mock_genai,
        "google.genai.types": mock_types,
    }
    return mock_genai, mock_types, modules


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


    def test_extract_json_unwraps_single_item_array(self) -> None:
        result = _extract_json_payload('[{"key": "value", "count": 3}]')
        self.assertEqual(result, {"key": "value", "count": 3})

    def test_extract_json_leaves_multi_item_array_intact(self) -> None:
        result = _extract_json_payload('[{"a": 1}, {"b": 2}]')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_extract_json_leaves_plain_object_intact(self) -> None:
        result = _extract_json_payload('{"ok": true}')
        self.assertEqual(result, {"ok": True})

    def test_extract_json_unwraps_fenced_single_item_array(self) -> None:
        result = _extract_json_payload('```json\n[{"title": "hello"}]\n```')
        self.assertEqual(result, {"title": "hello"})


class TestDispatchGemini(unittest.TestCase):
    """Tests for _dispatch_gemini auth paths.  google-genai SDK is mocked via sys.modules."""

    def _dispatch(
        self,
        modules: dict,
        env: dict[str, str],
        model: str = "gemini:gemini-2.0-flash",
        prompt: str = "test",
    ) -> None:
        from orchestrator_utils import _dispatch_gemini

        with patch.dict(sys.modules, modules, clear=False), patch.dict(
            os.environ, env, clear=False
        ):
            _dispatch_gemini(model, prompt, None)

    def _stub_modules(self) -> tuple[MagicMock, dict]:
        mock_genai, _types, modules = _make_genai_mock()
        mock_resp = MagicMock()
        mock_resp.text = "stub response"
        mock_genai.Client.return_value.models.generate_content.return_value = mock_resp
        return mock_genai, modules

    def test_vertex_ai_missing_project_raises(self) -> None:
        _, modules = self._stub_modules()
        with self.assertRaises(ModelCallError) as ctx:
            self._dispatch(modules, {"GOOGLE_GENAI_USE_VERTEXAI": "1", "GOOGLE_CLOUD_PROJECT": ""})
        self.assertIn("GOOGLE_CLOUD_PROJECT", str(ctx.exception))

    def test_vertex_ai_passes_project_and_location(self) -> None:
        mock_genai, modules = self._stub_modules()
        self._dispatch(
            modules,
            {
                "GOOGLE_GENAI_USE_VERTEXAI": "1",
                "GOOGLE_CLOUD_PROJECT": "my-proj",
                "GOOGLE_CLOUD_LOCATION": "europe-west4",
            },
        )
        mock_genai.Client.assert_called_once_with(
            vertexai=True, project="my-proj", location="europe-west4"
        )

    def test_vertex_ai_defaults_location_to_us_central1(self) -> None:
        mock_genai, modules = self._stub_modules()
        self._dispatch(
            modules,
            {
                "GOOGLE_GENAI_USE_VERTEXAI": "1",
                "GOOGLE_CLOUD_PROJECT": "my-proj",
                "GOOGLE_CLOUD_LOCATION": "",
            },
        )
        mock_genai.Client.assert_called_once_with(
            vertexai=True, project="my-proj", location="us-central1"
        )

    def test_api_key_path_missing_key_raises(self) -> None:
        _, modules = self._stub_modules()
        with self.assertRaises(ModelCallError) as ctx:
            self._dispatch(modules, {"GOOGLE_GENAI_USE_VERTEXAI": "0", "GOOGLE_API_KEY": ""})
        self.assertIn("GOOGLE_API_KEY", str(ctx.exception))

    def test_api_key_path_uses_key(self) -> None:
        mock_genai, modules = self._stub_modules()
        self._dispatch(
            modules,
            {"GOOGLE_GENAI_USE_VERTEXAI": "0", "GOOGLE_API_KEY": "test-key-123"},
        )
        mock_genai.Client.assert_called_once_with(api_key="test-key-123")


if __name__ == "__main__":
    unittest.main()
