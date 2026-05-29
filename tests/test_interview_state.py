"""
InterviewState 单元测试：维度覆盖、终止条件、红旗信号、序列化
"""
import unittest
from medagentcare.swarm.interview_state import (
    InterviewState,
    REQUIRED_DIMENSIONS,
    RED_FLAG_RULES,
)


class TestInterviewState(unittest.TestCase):
    """InterviewState 数据模型单测"""

    def setUp(self):
        self.state = InterviewState(
            session_id="test-session-001",
            chief_complaint="头痛3天，伴恶心",
        )

    # ===== 基础属性 =====

    def test_initial_state(self):
        """初始状态正确"""
        self.assertEqual(self.state.session_id, "test-session-001")
        self.assertEqual(self.state.chief_complaint, "头痛3天，伴恶心")
        self.assertEqual(self.state.current_round, 0)
        self.assertEqual(self.state.max_rounds, 5)
        self.assertEqual(len(self.state.remaining_dimensions), 8)
        self.assertFalse(self.state.interview_complete)

    # ===== 维度操作 =====

    def test_mark_dimension_covered(self):
        """标记维度已覆盖"""
        self.assertIn("部位", self.state.remaining_dimensions)
        self.state.mark_dimension_covered("部位")
        self.assertNotIn("部位", self.state.remaining_dimensions)
        self.assertIn("部位", self.state.covered_dimensions)

    def test_mark_dimension_covered_idempotent(self):
        """重复标记同一维度不报错"""
        self.state.mark_dimension_covered("部位")
        self.state.mark_dimension_covered("部位")  # 不应报错
        self.assertEqual(self.state.covered_dimensions.count("部位"), 1)

    def test_mark_dimension_skipped(self):
        """标记维度已跳过"""
        self.assertIn("部位", self.state.remaining_dimensions)
        self.state.mark_dimension_skipped("部位")
        self.assertNotIn("部位", self.state.remaining_dimensions)
        self.assertIn("部位", self.state.skipped_dimensions)

    def test_retry_dimension_logic(self):
        """追问重试逻辑：松一次 → 紧一次 → 跳过"""
        # 第一次重试：继续追问
        self.assertTrue(self.state.retry_dimension("部位"))
        self.assertIn("部位", self.state.remaining_dimensions)

        # 第二次重试：继续追问
        self.assertTrue(self.state.retry_dimension("部位"))

        # 第三次重试：跳过
        self.assertFalse(self.state.retry_dimension("部位"))
        self.assertIn("部位", self.state.skipped_dimensions)
        self.assertNotIn("部位", self.state.remaining_dimensions)

    # ===== 终止条件 =====

    def test_complete_when_all_dimensions_covered(self):
        """所有维度覆盖 → 自动完成"""
        for dim in REQUIRED_DIMENSIONS:
            self.state.mark_dimension_covered(dim)
        self.assertTrue(self.state.check_completion())
        self.assertTrue(self.state.interview_complete)

    def test_complete_when_max_rounds_reached(self):
        """达到最大轮次 → 自动完成"""
        self.state.max_rounds = 3
        self.state.current_round = 3
        self.assertTrue(self.state.check_completion())

    def test_complete_when_user_exits(self):
        """用户提前终止"""
        self.state.user_requested_early_exit = True
        self.assertTrue(self.state.check_completion())

    def test_not_complete_when_dimensions_remain(self):
        """维度未覆盖完、轮次未到、用户未退出 → 不终止"""
        self.state.mark_dimension_covered("部位")
        self.state.current_round = 2
        self.assertFalse(self.state.check_completion())

    # ===== 红旗信号 =====

    def test_add_red_flag(self):
        """添加红旗信号并自动压缩轮次"""
        self.state.add_red_flag("胸痛")
        self.assertIn("胸痛", self.state.red_flags)
        self.assertTrue(self.state.has_red_flags())
        self.assertLessEqual(self.state.max_rounds, 3)

    def test_emergency_detection(self):
        """紧急红旗信号识别"""
        self.state.add_red_flag("突发言语不清")
        self.assertTrue(self.state.is_emergency())

        state2 = InterviewState(session_id="t2", chief_complaint="头痛")
        state2.add_red_flag("头痛")  # 不在紧急列表中
        self.assertFalse(state2.is_emergency())

    def test_duplicate_red_flag(self):
        """重复红旗不重复添加"""
        self.state.add_red_flag("胸痛")
        self.state.add_red_flag("胸痛")
        self.assertEqual(len(self.state.red_flags), 1)

    # ===== 回答记录 =====

    def test_add_answer(self):
        """记录问答"""
        self.state.current_round = 1
        self.state.add_answer("哪里不舒服？", "前额部位", "部位")
        self.assertEqual(len(self.state.collected_answers), 1)
        self.assertEqual(self.state.collected_answers[0]["dimension"], "部位")
        self.assertEqual(self.state.collected_answers[0]["answer"], "前额部位")

    def test_build_summary(self):
        """问诊摘要生成"""
        self.state.current_round = 1
        self.state.mark_dimension_covered("部位")
        self.state.mark_dimension_covered("时间/病程")
        self.state.mark_dimension_skipped("用药史")
        self.state.add_answer("哪里不舒服？", "前额部位", "部位")
        self.state.add_answer("持续多久了？", "3天", "时间/病程")

        summary = self.state.build_summary()
        self.assertIn("主诉：头痛3天，伴恶心", summary)
        self.assertIn("已覆盖维度：部位, 时间/病程", summary)
        self.assertIn("跳过的维度：用药史", summary)
        self.assertIn("前额部位", summary)
        self.assertIn("3天", summary)

    # ===== 序列化 =====

    def test_round_trip_serialization(self):
        """序列化往返一致性"""
        self.state.current_round = 2
        self.state.mark_dimension_covered("部位")
        self.state.mark_dimension_covered("时间/病程")
        self.state.mark_dimension_skipped("用药史")
        self.state.add_red_flag("剧烈头痛")
        self.state.add_answer("哪里不舒服？", "前额", "部位")

        data = self.state.to_dict()
        restored = InterviewState.from_dict(data)

        self.assertEqual(restored.session_id, self.state.session_id)
        self.assertEqual(restored.chief_complaint, self.state.chief_complaint)
        self.assertEqual(restored.current_round, 2)
        self.assertEqual(restored.max_rounds, 3)  # 红旗压缩后
        self.assertEqual(restored.covered_dimensions, ["部位", "时间/病程"])
        self.assertEqual(restored.skipped_dimensions, ["用药史"])
        self.assertEqual(restored.red_flags, ["剧烈头痛"])
        self.assertEqual(len(restored.collected_answers), 1)


class TestRequiredDimensions(unittest.TestCase):
    """必问维度配置验证"""

    def test_eight_required_dimensions(self):
        self.assertEqual(len(REQUIRED_DIMENSIONS), 8)
        expected = [
            "部位", "时间/病程", "性质", "严重程度",
            "诱因/缓解因素", "伴随症状", "既往史", "用药史",
        ]
        self.assertEqual(REQUIRED_DIMENSIONS, expected)

    def test_red_flag_rules_configured(self):
        self.assertGreaterEqual(len(RED_FLAG_RULES), 10)
        self.assertIn("胸痛", RED_FLAG_RULES)
        self.assertIn("突发言语不清", RED_FLAG_RULES)


if __name__ == "__main__":
    unittest.main()
