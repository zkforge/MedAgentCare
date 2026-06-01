import tempfile
import unittest

from medagentcare.memory.conversation_store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def test_create_append_and_restore_recent_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(tmp)
            session = store.create_session(session_id="session-1")

            updated = store.append_turn(
                session_id=session["id"],
                question="最近一周胸闷气短，活动后更明显",
                result={
                    "answer": "建议尽快就医评估。",
                    "session_id": session["id"],
                    "suggestions": ["尽快就医"],
                    "disclaimer": "仅供参考",
                    "progress_events": [{"stage": "hidden"}],
                },
            )

            self.assertEqual(updated["title"], "最近一周胸闷气短，活动后更明显")
            self.assertEqual(len(store.get_session(session["id"])["messages"]), 2)
            self.assertEqual(
                store.recent_history(session["id"]),
                [
                    {"role": "user", "content": "最近一周胸闷气短，活动后更明显"},
                    {"role": "assistant", "content": "建议尽快就医评估。"},
                ],
            )
            assistant = store.get_session(session["id"])["messages"][1]
            self.assertNotIn("progress_events", assistant["response"])

    def test_interview_state_is_persisted_and_cleared_after_final_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(tmp)
            store.create_session(session_id="session-2")

            store.append_turn(
                session_id="session-2",
                question="我最近头痛怎么办",
                result={
                    "status": "need_more_info",
                    "answer": "请补充头痛部位。",
                    "session_id": "session-2",
                    "interview_state": {"session_id": "session-2", "chief_complaint": "头痛"},
                },
            )
            self.assertEqual(store.get_interview_state("session-2")["chief_complaint"], "头痛")

            store.append_turn(
                session_id="session-2",
                question="前额痛",
                result={
                    "answer": "建议观察高危信号。",
                    "session_id": "session-2",
                },
            )
            self.assertIsNone(store.get_interview_state("session-2"))

    def test_delete_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(tmp)
            store.create_session(session_id="session-3")

            self.assertTrue(store.delete_session("session-3"))
            self.assertEqual(store.list_sessions(), [])
            self.assertFalse(store.delete_session("session-3"))


if __name__ == "__main__":
    unittest.main()
