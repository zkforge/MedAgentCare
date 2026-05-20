import unittest
from pathlib import Path

from medagentcare.core.skill_loader import discover_skills


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SkillDiscoveryTests(unittest.TestCase):
    def test_discovers_expected_local_skills(self):
        skills = discover_skills(project_root=PROJECT_ROOT)
        discovered_names = {skill["name"] for skill in skills}

        self.assertEqual(len(skills), 9)
        self.assertEqual(
            discovered_names,
            {
                "analyze-symptoms",
                "assess-risk",
                "clinical-guideline",
                "deep-research",
                "disease-code",
                "recommend-lifestyle",
                "search-history",
                "search-knowledge",
                "search-similar-cases",
            },
        )

    def test_discovered_skills_expose_callable_functions(self):
        skills = discover_skills(project_root=PROJECT_ROOT)

        for skill in skills:
            self.assertTrue(callable(skill["function"]), skill["name"])
            self.assertTrue(skill["function_name"])
            self.assertTrue(skill["script_name"])
            self.assertIsInstance(skill["metadata"], dict)


if __name__ == "__main__":
    unittest.main()
