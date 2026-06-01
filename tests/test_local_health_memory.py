import tempfile
import unittest
from pathlib import Path

from medagentcare.memory.local_health_memory import LocalHealthMemory


class LocalHealthMemoryTests(unittest.TestCase):
    def test_raw_session_is_saved_without_confirmed_summary_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = LocalHealthMemory(tmp)

            memory.save_raw_session(
                session_id="session-1",
                question="最近一周胸闷气短，活动后更明显",
                answer="建议尽快就医评估。",
                suggestions=["尽快就医"],
                disclaimer="仅供参考",
                backend="local",
            )

            snapshot = memory.list_memory()
            self.assertEqual(snapshot["status"]["raw_count"], 1)
            self.assertEqual(snapshot["status"]["summary_count"], 0)
            self.assertEqual(snapshot["summaries"], [])

    def test_confirmed_local_summary_is_indexed_and_searchable(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = LocalHealthMemory(tmp)
            memory.save_raw_session(
                session_id="session-2",
                question="最近一周胸闷气短，活动后更明显",
                answer="建议尽快就医评估。",
                suggestions=["尽快就医"],
                disclaimer="仅供参考",
                backend="local",
            )

            entry = memory.confirm_summary(
                session_id="session-2",
                backend="local",
                summary={
                    "title": "胸闷气短伴出冷汗",
                    "summary": "用户最近一周胸闷气短，活动后更明显，建议尽快就医评估。",
                    "tags": ["胸闷", "气短"],
                    "urgency": "high",
                    "timeline": "最近一周",
                    "care_recommendation": "尽快就医。",
                    "profile_candidates": [],
                },
            )

            self.assertEqual(entry["session_id"], "session-2")
            hits = memory.search("胸闷气短是否需要就医")
            self.assertEqual(hits[0]["session_id"], "session-2")
            self.assertTrue(Path(tmp, "users", "local_default", "session_summaries", "session-2.md").exists())

    def test_delete_session_removes_raw_and_confirmed_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = LocalHealthMemory(tmp)
            memory.save_raw_session(
                session_id="session-3",
                question="头痛发热",
                answer="建议观察。",
                backend="local",
            )
            memory.confirm_summary(
                session_id="session-3",
                backend="local",
                summary={
                    "title": "头痛发热",
                    "summary": "用户头痛发热，建议观察高危信号。",
                    "tags": ["头痛", "发热"],
                },
            )

            deleted = memory.delete_session("session-3")

            self.assertTrue(deleted["raw"])
            self.assertTrue(deleted["summary"])
            self.assertEqual(memory.list_memory()["status"]["raw_count"], 0)
            self.assertEqual(memory.search("头痛发热"), [])


if __name__ == "__main__":
    unittest.main()
