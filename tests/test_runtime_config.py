import importlib
import os
import tempfile
import tomllib
from pathlib import Path
import unittest
from unittest.mock import patch


class RuntimeConfigTests(unittest.TestCase):
    def _reload_config(self):
        import medagentcare.config as config

        return importlib.reload(config)

    def test_llm_config_reads_environment_variables(self):
        env = {
            "LLM_API_KEY": "test-api-key",
            "LLM_MODEL_NAME": "test-model",
            "LLM_BASE_URL": "https://llm.example.test/v1",
            "LLM_TEMPERATURE": "0.2",
            "LLM_MAX_TOKENS": "1024",
            "MEM0_API_KEY": "test-mem0-key",
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "test-langsmith-key",
            "LANGSMITH_PROJECT": "test-langsmith-project",
            "LANGSMITH_ENDPOINT": "https://smith.example.test",
        }

        with patch.dict(os.environ, env, clear=True):
            config = self._reload_config()

        self.assertEqual(config.LLM_CONFIG["api_key"], "test-api-key")
        self.assertEqual(config.LLM_CONFIG["model_name"], "test-model")
        self.assertEqual(config.LLM_CONFIG["base_url"], "https://llm.example.test/v1")
        self.assertEqual(config.LLM_CONFIG["temperature"], 0.2)
        self.assertEqual(config.LLM_CONFIG["max_tokens"], 1024)
        self.assertEqual(config.MEM0_CONFIG["api_key"], "test-mem0-key")
        self.assertTrue(config.LANGSMITH_CONFIG["tracing"])
        self.assertEqual(config.LANGSMITH_CONFIG["api_key"], "test-langsmith-key")
        self.assertEqual(config.LANGSMITH_CONFIG["project"], "test-langsmith-project")
        self.assertEqual(config.LANGSMITH_CONFIG["endpoint"], "https://smith.example.test")

    def test_openai_api_key_is_supported_as_llm_fallback(self):
        with patch.dict(
            os.environ,
            {
                "MEDAGENTCARE_SKIP_DOTENV": "1",
                "OPENAI_API_KEY": "fallback-key",
            },
            clear=True,
        ):
            config = self._reload_config()

        self.assertEqual(config.LLM_CONFIG["api_key"], "fallback-key")

    def test_missing_optional_keys_default_to_empty_strings(self):
        with patch.dict(os.environ, {"MEDAGENTCARE_SKIP_DOTENV": "1"}, clear=True):
            config = self._reload_config()

        self.assertEqual(config.LLM_CONFIG["api_key"], "")
        self.assertEqual(config.MEM0_CONFIG["api_key"], "")

    def test_dotenv_file_is_loaded_for_local_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "LLM_API_KEY=dotenv-api-key",
                        "LLM_MODEL_NAME=dotenv-model",
                        "LLM_BASE_URL=https://dotenv.example.test/v1",
                        "MEM0_API_KEY=dotenv-mem0-key",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"MEDAGENTCARE_DOTENV_PATH": str(dotenv_path)},
                clear=True,
            ):
                config = self._reload_config()

        self.assertEqual(config.LLM_CONFIG["api_key"], "dotenv-api-key")
        self.assertEqual(config.LLM_CONFIG["model_name"], "dotenv-model")
        self.assertEqual(config.LLM_CONFIG["base_url"], "https://dotenv.example.test/v1")
        self.assertEqual(config.MEM0_CONFIG["api_key"], "dotenv-mem0-key")

    def test_real_environment_values_override_dotenv_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text("LLM_API_KEY=dotenv-api-key\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "MEDAGENTCARE_DOTENV_PATH": str(dotenv_path),
                    "LLM_API_KEY": "real-env-api-key",
                },
                clear=True,
            ):
                config = self._reload_config()

        self.assertEqual(config.LLM_CONFIG["api_key"], "real-env-api-key")

    def test_milvus_lite_extra_is_declared_for_local_database(self):
        project_root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((project_root / "pyproject.toml").read_text())
        dependencies = set(pyproject["project"]["dependencies"])

        self.assertIn("pymilvus[milvus_lite]>=2.3.0", dependencies)
        self.assertNotIn("pymilvus>=2.3.0", dependencies)


if __name__ == "__main__":
    unittest.main()
