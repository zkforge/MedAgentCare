import importlib
import os
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
        }

        with patch.dict(os.environ, env, clear=True):
            config = self._reload_config()

        self.assertEqual(config.LLM_CONFIG["api_key"], "test-api-key")
        self.assertEqual(config.LLM_CONFIG["model_name"], "test-model")
        self.assertEqual(config.LLM_CONFIG["base_url"], "https://llm.example.test/v1")
        self.assertEqual(config.LLM_CONFIG["temperature"], 0.2)
        self.assertEqual(config.LLM_CONFIG["max_tokens"], 1024)
        self.assertEqual(config.MEM0_CONFIG["api_key"], "test-mem0-key")

    def test_openai_api_key_is_supported_as_llm_fallback(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fallback-key"}, clear=True):
            config = self._reload_config()

        self.assertEqual(config.LLM_CONFIG["api_key"], "fallback-key")

    def test_missing_optional_keys_default_to_empty_strings(self):
        with patch.dict(os.environ, {}, clear=True):
            config = self._reload_config()

        self.assertEqual(config.LLM_CONFIG["api_key"], "")
        self.assertEqual(config.MEM0_CONFIG["api_key"], "")


if __name__ == "__main__":
    unittest.main()
