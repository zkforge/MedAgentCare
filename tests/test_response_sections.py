import unittest

from medagentcare.response_sections import (
    DEFAULT_MEDICAL_DISCLAIMER,
    extract_suggestions,
    strip_structured_sections,
    structure_medical_response,
)


class ResponseSectionTests(unittest.TestCase):
    def test_structures_answer_without_duplicate_sections(self):
        text = """【回答】
发热头痛两天，合并高血压史时，需要重点观察体温、血压和神经系统症状。

【核心建议】
1. 监测体温和血压，每天记录变化。
2、注意补液和休息，避免自行叠加用药。
- 若出现剧烈头痛、意识异常或血压明显升高，应及时就医。

【免责声明】
以上信息仅供参考，不能替代专业医生的诊断和治疗。"""

        structured = structure_medical_response(text)

        self.assertIn("发热头痛两天", structured.answer)
        self.assertNotIn("核心建议", structured.answer)
        self.assertNotIn("免责声明", structured.answer)
        self.assertEqual(
            structured.suggestions,
            [
                "监测体温和血压，每天记录变化。",
                "注意补液和休息，避免自行叠加用药。",
                "若出现剧烈头痛、意识异常或血压明显升高，应及时就医。",
            ],
        )
        self.assertEqual(
            structured.disclaimer,
            "以上信息仅供参考，不能替代专业医生的诊断和治疗。",
        )

    def test_suggestions_support_chinese_numbering_and_multiline_items(self):
        text = """【核心建议】
一、先休息并补充水分
如果持续高热，应记录体温变化。
（2）避免自行加大降压药或退烧药剂量
3) 出现胸痛、呼吸困难、意识异常时立即就医
"""

        self.assertEqual(
            extract_suggestions(text),
            [
                "先休息并补充水分 如果持续高热，应记录体温变化。",
                "避免自行加大降压药或退烧药剂量",
                "出现胸痛、呼吸困难、意识异常时立即就医",
            ],
        )

    def test_suggestions_preserve_inline_markdown(self):
        text = """【核心建议】
1. **立即启动双重监测**：记录体温和血压变化。
2. **及时就医**：出现意识异常或剧烈头痛时立即就医。
"""

        self.assertEqual(
            extract_suggestions(text),
            [
                "**立即启动双重监测**：记录体温和血压变化。",
                "**及时就医**：出现意识异常或剧烈头痛时立即就医。",
            ],
        )

    def test_heading_only_core_suggestions_are_not_returned(self):
        text = """【回答】
先观察症状变化。

【核心建议】
核心建议

【免责声明】
"""

        structured = structure_medical_response(
            text,
            fallback_suggestions=["请遵循医嘱，注意休息和营养"],
        )

        self.assertEqual(structured.suggestions, ["请遵循医嘱，注意休息和营养"])
        self.assertEqual(structured.disclaimer, DEFAULT_MEDICAL_DISCLAIMER)

    def test_structured_only_response_does_not_fall_back_to_duplicate_body(self):
        text = """【核心建议】
1. 记录体温。

【免责声明】
仅供参考。"""

        structured = structure_medical_response(text)

        self.assertEqual(structured.answer, "")
        self.assertEqual(structured.suggestions, ["记录体温。"])
        self.assertEqual(structured.disclaimer, "仅供参考。")

    def test_strip_preserves_non_structured_medical_sections(self):
        text = """【风险评估】
目前属于需要密切观察的情况。

【核心建议】
1. 记录症状。

【诊断分析】
不能仅凭描述明确诊断。

【免责声明】
仅供参考。"""

        stripped = strip_structured_sections(text)

        self.assertIn("【风险评估】", stripped)
        self.assertIn("【诊断分析】", stripped)
        self.assertNotIn("核心建议", stripped)
        self.assertNotIn("免责声明", stripped)


if __name__ == "__main__":
    unittest.main()
