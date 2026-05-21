import asyncio
import importlib
import json
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

    def test_chat_stream_emits_result_event(self):
        api = _load_api_with_env({})
        fake_swarm = types.ModuleType("medagentcare.swarm")
        captured = {}

        async def fake_process_with_swarm(**kwargs):
            captured.update(kwargs)
            progress_callback = kwargs["progress_callback"]
            await progress_callback(
                {
                    "stage": "lead_assessment",
                    "title": "分析问题复杂度",
                    "detail": "判断是否需要多 Agent 协作。",
                    "status": "running",
                    "metadata": {},
                }
            )
            await asyncio.sleep(0.01)
            await progress_callback(
                {
                    "stage": "synthesis",
                    "title": "结果汇总完成",
                    "detail": "最终医学咨询回答已生成。",
                    "status": "completed",
                    "metadata": {},
                }
            )
            return {"answer": "ok", "swarm_enabled": kwargs["enable_swarm"]}

        fake_swarm.process_with_swarm = fake_process_with_swarm

        async def collect_events():
            request = api.ChatRequest(
                question="头痛怎么办？",
                enable_swarm=False,
                session_id="stream-test",
            )
            chunks = []
            with patch.dict(sys.modules, {"medagentcare.swarm": fake_swarm}):
                async for chunk in api._stream_chat_events(request, heartbeat_interval=0.001):
                    chunks.append(chunk)
            return "".join(chunks)

        body = asyncio.run(collect_events())

        self.assertIn("event: start", body)
        self.assertIn("event: progress", body)
        self.assertIn("event: heartbeat", body)
        self.assertIn("event: result", body)
        self.assertIn("event: done", body)
        self.assertIn("分析问题复杂度", body)
        self.assertIn("结果汇总完成", body)
        self.assertFalse(captured["enable_swarm"])
        self.assertEqual(captured["session_id"], "stream-test")

    def test_chat_stream_maps_business_errors_to_error_event(self):
        api = _load_api_with_env({})
        fake_swarm = types.ModuleType("medagentcare.swarm")

        async def fake_process_with_swarm(**kwargs):
            raise ValueError("invalid routing input")

        fake_swarm.process_with_swarm = fake_process_with_swarm

        async def collect_events():
            request = api.ChatRequest(question="头痛怎么办？")
            chunks = []
            with patch.dict(sys.modules, {"medagentcare.swarm": fake_swarm}):
                async for chunk in api._stream_chat_events(request, heartbeat_interval=0.001):
                    chunks.append(chunk)
            return "".join(chunks)

        body = asyncio.run(collect_events())
        error_line = next(
            line.removeprefix("data: ")
            for line in body.splitlines()
            if line.startswith("data: ") and "invalid routing input" in line
        )
        error_payload = json.loads(error_line)

        self.assertIn("event: error", body)
        self.assertEqual(error_payload["status_code"], 400)
        self.assertEqual(error_payload["detail"], "invalid routing input")

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
