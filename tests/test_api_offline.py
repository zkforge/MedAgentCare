import asyncio
import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import HTTPException


def _load_api_with_env(env):
    with patch.dict(os.environ, env, clear=True):
        import medagentcare.config as config

        importlib.reload(config)

        import medagentcare.api as api

        return importlib.reload(api)


class ApiOfflineTests(unittest.TestCase):
    def test_health_reports_configuration_readiness(self):
        api = _load_api_with_env(
            {
                "LLM_API_KEY": "test-api-key",
                "MEM0_API_KEY": "",
            }
        )

        result = asyncio.run(api.health())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["service"], "medagentcare")
        self.assertTrue(result["llm_configured"])
        self.assertFalse(result["mem0_configured"])

    def test_chat_passes_swarm_disabled_flag_to_runtime(self):
        api = _load_api_with_env({})
        fake_swarm = types.ModuleType("medagentcare.swarm")
        captured = {}

        async def fake_process_with_swarm(**kwargs):
            captured.update(kwargs)
            return {"answer": "ok", "swarm_enabled": kwargs["enable_swarm"]}

        fake_swarm.process_with_swarm = fake_process_with_swarm

        request = api.ChatRequest(question="头痛怎么办？", enable_swarm=False, session_id="offline-test")
        with patch.dict(sys.modules, {"medagentcare.swarm": fake_swarm}):
            result = asyncio.run(api.chat(request))

        self.assertEqual(result["answer"], "ok")
        self.assertFalse(result["swarm_enabled"])
        self.assertFalse(captured["enable_swarm"])
        self.assertEqual(captured["session_id"], "offline-test")

    def test_chat_maps_business_validation_errors_to_400(self):
        api = _load_api_with_env({})
        fake_swarm = types.ModuleType("medagentcare.swarm")

        async def fake_process_with_swarm(**kwargs):
            raise ValueError("invalid routing input")

        fake_swarm.process_with_swarm = fake_process_with_swarm

        request = api.ChatRequest(question="头痛怎么办？")
        with patch.dict(sys.modules, {"medagentcare.swarm": fake_swarm}):
            with self.assertRaises(HTTPException) as exc_info:
                asyncio.run(api.chat(request))

        self.assertEqual(exc_info.exception.status_code, 400)
        self.assertEqual(exc_info.exception.detail, "invalid routing input")

    def test_chat_maps_runtime_errors_to_500(self):
        api = _load_api_with_env({})
        fake_swarm = types.ModuleType("medagentcare.swarm")

        async def fake_process_with_swarm(**kwargs):
            raise RuntimeError("llm unavailable")

        fake_swarm.process_with_swarm = fake_process_with_swarm

        request = api.ChatRequest(question="头痛怎么办？")
        with patch.dict(sys.modules, {"medagentcare.swarm": fake_swarm}):
            with self.assertRaises(HTTPException) as exc_info:
                asyncio.run(api.chat(request))

        self.assertEqual(exc_info.exception.status_code, 500)
        self.assertEqual(exc_info.exception.detail, "consultation failed: llm unavailable")


if __name__ == "__main__":
    unittest.main()
