"""
Interview 路由集成测试：症状检测、问诊流程、状态转换
"""
import asyncio
import unittest

from medagentcare.swarm.swarm_coordinator import SwarmCoordinator
from medagentcare.swarm.interview_state import InterviewState


# ===== 测试用的 Fake/Mock 对象 =====

class _FakeShortTermMemory:
    """支持 interview_state 的 Fake 短期记忆"""

    def __init__(self):
        self.storage_type = "memory"
        self._interview_states = {}

    def get_recent_messages(self, session_id, limit=10):
        return []

    def get_interview_state(self, session_id):
        return self._interview_states.get(session_id)

    def set_interview_state(self, session_id, state):
        self._interview_states[session_id] = state

    def has_active_interview(self, session_id):
        state = self._interview_states.get(session_id)
        return state is not None and not state.interview_complete

    def clear_interview_state(self, session_id):
        self._interview_states.pop(session_id, None)

    def add_message(self, session_id, role, content):
        pass


class _FakeLongTermMemory:
    enabled = False

    def search_similar_sessions(self, query, limit=3):
        return []

    def add_session_summary(self, **kwargs):
        return None


class _FakeLeadAgent:
    """不参与问诊路由的 LeadAgent"""
    assess_called = False

    async def assess_and_decompose(self, question, context=None):
        self.assess_called = True
        return {"subtasks": []}


class _FakeConsultationAgent:
    agent_id = "consultation_agent"
    process_called = False

    async def process(self, input_data):
        self.process_called = True
        return {
            "answer": "建议多休息，保持充足睡眠，如症状持续建议就医。",
            "suggestions": ["多休息"],
            "disclaimer": "以上信息仅供参考。",
        }


class _FakeInterviewAgent:
    """模拟 InterviewAgent 的行为"""
    agent_id = "interview_agent"

    def __init__(self, responses=None):
        """
        responses: 轮次 → 返回结果的列表，模拟多轮追问
        每轮可返回 need_more_info 或 interview_complete
        """
        self.responses = responses or []
        self.call_count = 0

    async def process(self, input_data):
        if self.call_count < len(self.responses):
            result = self.responses[self.call_count]
            self.call_count += 1
            return result
        # 默认返回追问
        self.call_count += 1
        return {
            "status": "need_more_info",
            "question": "还有什么其他不舒服吗？",
            "covered_dimension": "伴随症状",
        }


class SymptomDetectionTests(unittest.TestCase):
    """症状报告识别测试"""

    def test_symptom_report_person_symptom(self):
        """有人称 + 有症状 → 症状报告"""
        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        self.assertTrue(coordinator._is_symptom_report("我最近头痛怎么办"))
        self.assertTrue(coordinator._is_symptom_report("小孩发烧了要去医院吗"))
        self.assertTrue(coordinator._is_symptom_report("最近总是头晕乏力"))

    def test_symptom_report_family_member(self):
        """家人代述 → 症状报告"""
        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        self.assertTrue(coordinator._is_symptom_report("我奶奶最近胸闷气短"))
        self.assertTrue(coordinator._is_symptom_report("宝宝咳嗽好几天了"))

    def test_not_symptom_report_knowledge_question(self):
        """纯知识问答不触发"""
        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        self.assertFalse(coordinator._is_symptom_report("高血压的治疗方案有哪些"))
        self.assertFalse(coordinator._is_symptom_report("二甲双胍的副作用是什么"))
        self.assertFalse(coordinator._is_symptom_report("糖尿病的诊断标准是什么"))

    def test_not_symptom_report_no_person(self):
        """无人称 → 不是症状报告"""
        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        self.assertFalse(coordinator._is_symptom_report("头痛的治疗方法"))
        self.assertFalse(coordinator._is_symptom_report("感冒吃什么药"))

    def test_symptom_report_with_consultation_intent(self):
        """有咨询意图的症状报告"""
        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        self.assertTrue(coordinator._is_symptom_report("我感冒了要不要吃药"))
        self.assertTrue(coordinator._is_symptom_report("最近失眠严重怎么办"))

    def test_early_exit_detection(self):
        """提前终止意图检测"""
        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        self.assertTrue(coordinator._has_early_exit_intent("别问了，直接告诉我吧"))
        self.assertTrue(coordinator._has_early_exit_intent("能不能直接告诉我结果"))
        self.assertFalse(coordinator._has_early_exit_intent("继续问吧"))
        self.assertFalse(coordinator._has_early_exit_intent("好的"))


class InterviewRoutingTests(unittest.TestCase):
    """问诊路由流程测试"""

    def setUp(self):
        self.coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        self.coordinator.enable_swarm = True
        self.coordinator.progress_callback = None
        self.coordinator.short_term_memory = _FakeShortTermMemory()
        self.coordinator.long_term_memory = _FakeLongTermMemory()
        self.coordinator.lead_agent = _FakeLeadAgent()
        self.coordinator.consultation_agent = _FakeConsultationAgent()

    def test_new_symptom_report_triggers_interview(self):
        """新症状报告 → 启动问诊模式"""
        self.coordinator.interview_agent = _FakeInterviewAgent(responses=[
            {
                "status": "need_more_info",
                "question": "头痛持续多久了？是一阵一阵的还是持续的？",
                "covered_dimension": "时间/病程",
                "red_flag_detected": None,
            },
        ])

        result = asyncio.run(
            self.coordinator.process(
                "我最近头痛怎么办",
                session_id="test-interview-start",
            )
        )

        self.assertEqual(result["status"], "need_more_info")
        self.assertIn("时间/病程", result.get("covered_dimensions", []))
        self.assertEqual(result["session_id"], "test-interview-start")

    def test_existing_interview_continues(self):
        """已有活跃问诊 → 继续追问"""
        # 先创建一个活跃的 interview state
        active_state = InterviewState(
            session_id="test-interview-continue",
            chief_complaint="头痛3天",
            current_round=1,
        )
        active_state.mark_dimension_covered("部位")
        self.coordinator.short_term_memory.set_interview_state(
            "test-interview-continue", active_state
        )

        self.coordinator.interview_agent = _FakeInterviewAgent(responses=[
            {
                "status": "need_more_info",
                "question": "疼痛的性质是怎样的？刺痛还是胀痛？",
                "covered_dimension": "性质",
            },
        ])

        result = asyncio.run(
            self.coordinator.process(
                "前额部位",
                session_id="test-interview-continue",
            )
        )

        self.assertEqual(result["status"], "need_more_info")
        self.assertEqual(result["interview_round"], 2)
        self.assertIn("部位", result.get("covered_dimensions", []))

    def test_interview_complete_proceeds_to_diagnosis(self):
        """问诊完成 → 自动转入诊断"""
        # 创建接近完成的 interview state
        active_state = InterviewState(
            session_id="test-interview-done",
            chief_complaint="头痛3天",
            current_round=4,
            max_rounds=5,
        )
        for dim in ["部位", "时间/病程", "性质", "严重程度", "诱因/缓解因素", "伴随症状", "既往史"]:
            active_state.mark_dimension_covered(dim)

        self.coordinator.short_term_memory.set_interview_state(
            "test-interview-done", active_state
        )

        self.coordinator.interview_agent = _FakeInterviewAgent(responses=[
            {
                "status": "interview_complete",
                "interview_summary": "患者头痛3天，前额部位，搏动性疼痛...",
                "interview_complete": True,
            },
        ])
        self.coordinator.consultation_agent = _FakeConsultationAgent()

        result = asyncio.run(
            self.coordinator.process(
                "没有在吃药",
                session_id="test-interview-done",
            )
        )

        # 问诊完成后应该走了 LeadAgent → 降级到 ConsultationAgent
        self.assertTrue(self.coordinator.lead_agent.assess_called)

    def test_early_exit_during_interview(self):
        """用户提前终止问诊 → 标记退出并转入诊断"""
        active_state = InterviewState(
            session_id="test-early-exit",
            chief_complaint="头痛",
            current_round=2,
        )
        active_state.mark_dimension_covered("部位")
        self.coordinator.short_term_memory.set_interview_state(
            "test-early-exit", active_state
        )

        result = asyncio.run(
            self.coordinator.process(
                "别问了，直接告诉我怎么办",
                session_id="test-early-exit",
            )
        )

        # 提前退出后转入诊断流程，走 LeadAgent → ConsultationAgent
        self.assertTrue(self.coordinator.lead_agent.assess_called)
        # 验证 state 被标记为提前退出
        updated_state = self.coordinator.short_term_memory.get_interview_state(
            "test-early-exit"
        )
        self.assertTrue(updated_state.user_requested_early_exit)
        self.assertTrue(updated_state.interview_complete)


class InterviewStateTransitionTests(unittest.TestCase):
    """问诊状态转换测试"""

    def test_state_persists_across_requests(self):
        """状态跨请求持久化（模拟多轮对话）"""
        memory = _FakeShortTermMemory()

        # 第一轮：创建新问诊
        state = InterviewState(
            session_id="multi-round",
            chief_complaint="头痛",
            current_round=1,
        )
        state.mark_dimension_covered("部位")
        memory.set_interview_state("multi-round", state)

        # 第二轮：恢复状态
        restored = memory.get_interview_state("multi-round")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.current_round, 1)
        self.assertIn("部位", restored.covered_dimensions)
        self.assertNotIn("部位", restored.remaining_dimensions)

        # 继续问诊
        restored.current_round = 2
        restored.mark_dimension_covered("时间/病程")
        memory.set_interview_state("multi-round", restored)

        restored2 = memory.get_interview_state("multi-round")
        self.assertEqual(restored2.current_round, 2)
        self.assertIn("时间/病程", restored2.covered_dimensions)

    def test_state_cleared_on_session_clear(self):
        """会话清除时问诊状态也被清除"""
        memory = _FakeShortTermMemory()
        state = InterviewState(session_id="clear-test", chief_complaint="test")
        memory.set_interview_state("clear-test", state)
        self.assertTrue(memory.has_active_interview("clear-test"))

        memory.clear_interview_state("clear-test")
        self.assertFalse(memory.has_active_interview("clear-test"))


if __name__ == "__main__":
    unittest.main()
