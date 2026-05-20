import importlib.util
from pathlib import Path
import unittest


def _load_assess_risk():
    script_path = (
        Path(__file__).resolve().parents[1]
        / ".agents"
        / "skills"
        / "assess-risk"
        / "script"
        / "risk.py"
    )
    spec = importlib.util.spec_from_file_location("assess_risk_skill", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.assess_risk


class AssessRiskSkillTests(unittest.TestCase):
    def test_string_age_from_llm_tool_call_is_accepted(self):
        assess_risk = _load_assess_risk()

        result = assess_risk(symptoms="头痛、发热、胸闷", age="35")

        self.assertTrue(result["success"])
        self.assertIn(result["risk_level"], {"medium", "high", "emergency"})

    def test_age_with_unit_is_accepted(self):
        assess_risk = _load_assess_risk()

        result = assess_risk(symptoms="头痛", age="70岁")

        self.assertTrue(result["success"])
        self.assertEqual(result["risk_level"], "high")


if __name__ == "__main__":
    unittest.main()
