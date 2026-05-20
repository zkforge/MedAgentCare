import unittest

from medagentcare.constraints import ConstraintValidator


DISCLAIMER = "以上信息仅供参考，不能替代专业医生的诊断和治疗。"


class MedicalSafetyConstraintTests(unittest.TestCase):
    def setUp(self):
        self.validator = ConstraintValidator()

    def test_high_risk_symptom_requires_doctor_visit(self):
        output = f"患者描述胸痛和心悸，可能需要进一步观察。\n{DISCLAIMER}"

        result = self.validator.validate_output("diagnostic_agent", output)

        self.assertFalse(result["valid"])
        self.assertIn("高危症状未建议就医", result["violations"])
        self.assertIn("add_emergency_warning", result["auto_fixable"])

    def test_high_risk_symptom_with_doctor_visit_is_allowed(self):
        output = f"患者描述胸痛和心悸，建议立即就医或前往急诊评估。\n{DISCLAIMER}"

        result = self.validator.validate_output("diagnostic_agent", output)

        self.assertNotIn("高危症状未建议就医", result["violations"])

    def test_definitive_diagnosis_is_rejected_for_consultation_agent(self):
        output = f"根据你的描述，您患有高血压。\n{DISCLAIMER}"

        result = self.validator.validate_output("consultation_agent", output)

        self.assertFalse(result["valid"])
        self.assertIn("包含明确诊断（越界行为）", result["violations"])

    def test_definitive_diagnosis_is_rejected_for_diagnostic_agent(self):
        output = f"这些表现确诊为偏头痛。\n{DISCLAIMER}"

        result = self.validator.validate_output("diagnostic_agent", output)

        self.assertFalse(result["valid"])
        self.assertIn("包含明确诊断（越界行为）", result["violations"])

    def test_specific_prescription_dose_is_rejected(self):
        output = f"建议服用布洛芬 200mg。\n{DISCLAIMER}"

        result = self.validator.validate_output("consultation_agent", output)

        self.assertFalse(result["valid"])
        self.assertIn("包含具体药物处方（越界行为）", result["violations"])

    def test_medication_name_with_direct_dose_is_rejected(self):
        output = f"可使用硝苯地平20mg控制症状。\n{DISCLAIMER}"

        result = self.validator.validate_output("diagnostic_agent", output)

        self.assertFalse(result["valid"])
        self.assertIn("包含具体药物处方（越界行为）", result["violations"])


if __name__ == "__main__":
    unittest.main()
