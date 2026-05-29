import asyncio
import unittest

from medagentcare.swarm.swarm_coordinator import SwarmCoordinator


class _FakeShortTermMemory:
    def get_recent_messages(self, session_id, limit=10):
        return []

    def get_interview_state(self, session_id):
        return None

    def has_active_interview(self, session_id):
        return False


class _FakeLongTermMemory:
    enabled = False

    def __init__(self):
        self.saved_metadata = None
        self.search_called = False

    def search_similar_sessions(self, query, limit=3):
        self.search_called = True
        return []

    def add_session_summary(self, **kwargs):
        self.saved_metadata = kwargs.get("metadata")
        return None


class _FailingLeadAgent:
    async def assess_and_decompose(self, question, context=None):
        raise AssertionError("fast consultation path should not call LeadAgent")


class _FakeConsultationAgent:
    agent_id = "consultation_agent"

    async def process(self, input_data):
        return {
            "answer": "建议监测体温和血压，出现高危表现及时就医。",
            "suggestions": ["监测体温和血压"],
            "disclaimer": "以上信息仅供参考，不能替代专业医生的诊断和治疗。",
        }


class SwarmRoutingTests(unittest.TestCase):
    def test_headache_fever_with_hypertension_history_uses_fast_consultation(self):
        coordinator = object.__new__(SwarmCoordinator)
        coordinator.enable_swarm = True
        coordinator.progress_callback = None
        coordinator.short_term_memory = _FakeShortTermMemory()
        coordinator.long_term_memory = _FakeLongTermMemory()
        coordinator.lead_agent = _FailingLeadAgent()
        coordinator.consultation_agent = _FakeConsultationAgent()

        result = asyncio.run(
            coordinator.process(
                "35岁，头痛发热两天，体温38.2度，有高血压史，需要注意什么？",
                session_id="routing-test",
            )
        )

        self.assertFalse(result["swarm_enabled"])
        self.assertEqual(result["session_id"], "routing-test")
        self.assertEqual(result["route_reason"], "简单常见咨询快速路由到 consultation_agent")
        self.assertEqual(
            coordinator.long_term_memory.saved_metadata["mode"],
            "fast_consultation",
        )
        self.assertFalse(coordinator.long_term_memory.search_called)

    def test_high_risk_symptoms_do_not_use_fast_consultation(self):
        self.assertFalse(
            SwarmCoordinator._should_use_fast_consultation(
                "头痛发热伴意识模糊和颈项强直，需要注意什么？"
            )
        )

    def test_research_questions_do_not_use_fast_consultation(self):
        self.assertFalse(
            SwarmCoordinator._should_use_fast_consultation(
                "高血压最新诊疗指南是什么？"
            )
        )


if __name__ == "__main__":
    unittest.main()
