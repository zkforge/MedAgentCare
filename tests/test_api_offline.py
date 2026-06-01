import asyncio
import importlib
import json
import os
import sys
import tempfile
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

        request = api.ChatRequest(
            question="头痛怎么办？",
            enable_swarm=False,
            session_id="offline-test",
            memory={"enabled": True, "backend": "local"},
        )
        with patch.dict(sys.modules, {"medagentcare.swarm": fake_swarm}):
            result = asyncio.run(api.chat(request))

        self.assertEqual(result["answer"], "ok")
        self.assertFalse(result["swarm_enabled"])
        self.assertFalse(captured["enable_swarm"])
        self.assertEqual(captured["session_id"], "offline-test")
        self.assertEqual(captured["memory"], {"enabled": True, "backend": "local"})

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

    def test_memory_status_and_local_confirm_delete_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = _load_api_with_env({"MEDAGENTCARE_MEMORY_DIR": tmp})
            local_memory = api._local_memory()
            local_memory.save_raw_session(
                session_id="memory-api-test",
                question="最近一周胸闷气短",
                answer="建议尽快就医评估。",
                suggestions=["尽快就医"],
                disclaimer="仅供参考",
                backend="local",
            )

            status = asyncio.run(api.memory_status())
            self.assertEqual(status["local"]["raw_count"], 1)

            request = api.MemorySummaryConfirmRequest(
                backend="local",
                summary={
                    "title": "胸闷气短",
                    "summary": "用户最近一周胸闷气短，建议尽快就医评估。",
                    "tags": ["胸闷", "气短"],
                },
            )
            confirmed = asyncio.run(api.confirm_memory_summary("memory-api-test", request))
            self.assertEqual(confirmed["backend"], "local")

            snapshot = asyncio.run(api.memory_local())
            self.assertEqual(snapshot["status"]["summary_count"], 1)

            deleted = asyncio.run(api.delete_memory_session("memory-api-test"))
            self.assertTrue(deleted["deleted"]["raw"])
            self.assertTrue(deleted["deleted"]["summary"])

    def test_generate_memory_summary_normalizes_common_llm_type_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = _load_api_with_env({"MEDAGENTCARE_MEMORY_DIR": tmp})
            api._local_memory().save_raw_session(
                session_id="summary-drift-test",
                question="最近一周胸闷气短，活动后更明显，偶尔出冷汗",
                answer="建议尽快就医评估。",
                suggestions=["尽快就医", "记录症状变化"],
                disclaimer="仅供参考",
                backend="local",
            )
            fake_core = types.ModuleType("medagentcare.core")

            class FakeLLMClient:
                async def chat(self, messages, temperature=None, max_tokens=None):
                    return json.dumps(
                        {
                            "title": "胸闷气短伴出冷汗",
                            "summary": "用户最近一周胸闷气短，活动后更明显。",
                            "tags": "胸闷，气短，出冷汗",
                            "urgency": "high",
                            "timeline": "最近一周",
                            "care_recommendation": ["尽快就医", "记录症状变化"],
                            "profile_candidates": [
                                {
                                    "type": "symptom",
                                    "value": "胸闷气短",
                                    "evidence": "用户自述最近一周胸闷气短",
                                    "confidence": 1.0,
                                }
                            ],
                        },
                        ensure_ascii=False,
                    )

            fake_core.LLMClient = FakeLLMClient
            with patch.dict(sys.modules, {"medagentcare.core": fake_core}):
                result = asyncio.run(api.generate_memory_summary("summary-drift-test"))

            summary = result["summary"]
            self.assertEqual(summary["tags"], ["胸闷", "气短", "出冷汗"])
            self.assertEqual(summary["care_recommendation"], "尽快就医；记录症状变化")
            self.assertEqual(summary["profile_candidates"][0]["confidence"], "高")

    def test_sessions_endpoints_and_chat_persistence(self):
        with tempfile.TemporaryDirectory() as sessions_tmp, tempfile.TemporaryDirectory() as memory_tmp:
            api = _load_api_with_env({
                "MEDAGENTCARE_SESSIONS_DIR": sessions_tmp,
                "MEDAGENTCARE_MEMORY_DIR": memory_tmp,
            })
            fake_swarm = types.ModuleType("medagentcare.swarm")

            async def fake_process_with_swarm(**kwargs):
                return {
                    "answer": "建议观察症状变化。",
                    "session_id": kwargs["session_id"],
                    "swarm_enabled": kwargs["enable_swarm"],
                    "suggestions": ["记录症状"],
                    "disclaimer": "仅供参考",
                }

            fake_swarm.process_with_swarm = fake_process_with_swarm

            created = asyncio.run(api.create_session(api.SessionCreateRequest(session_id="session-api-test")))
            self.assertEqual(created["id"], "session-api-test")

            request = api.ChatRequest(question="头痛怎么办？", session_id="session-api-test")
            with patch.dict(sys.modules, {"medagentcare.swarm": fake_swarm}):
                result = asyncio.run(api.chat(request))

            self.assertEqual(result["answer"], "建议观察症状变化。")
            session = asyncio.run(api.get_session("session-api-test"))
            self.assertEqual(len(session["messages"]), 2)
            self.assertEqual(session["messages"][0]["role"], "user")
            self.assertEqual(session["messages"][1]["role"], "assistant")

            listed = asyncio.run(api.list_sessions())
            self.assertEqual(listed["sessions"][0]["id"], "session-api-test")
            self.assertEqual(listed["sessions"][0]["messages"], [])

            deleted = asyncio.run(api.delete_session("session-api-test"))
            self.assertTrue(deleted["deleted"])

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
