import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from medagentcare.knowledge.milvus_kb import MedicalKnowledgeBase


class _FakeVector:
    def tolist(self):
        return [0.1, 0.2]


class _FakeEmbeddingModel:
    def get_sentence_embedding_dimension(self):
        return 2

    def encode(self, values, show_progress_bar=False):
        return [_FakeVector() for _ in values]


class MedicalKnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        MedicalKnowledgeBase._instance = None

    def tearDown(self):
        MedicalKnowledgeBase._instance = None

    @patch("medagentcare.knowledge.milvus_kb.SentenceTransformer")
    @patch("medagentcare.knowledge.milvus_kb.MilvusClient")
    def test_existing_collection_is_loaded_before_search(self, mock_client_cls, mock_transformer):
        client = Mock()
        client.has_collection.return_value = True
        client.search.return_value = [
            [
                {
                    "id": 1,
                    "distance": 0.2,
                    "entity": {
                        "content": "测试内容",
                        "metadata": '{"type": "lifestyle"}',
                    },
                }
            ]
        ]
        mock_client_cls.return_value = client
        mock_transformer.return_value = _FakeEmbeddingModel()

        with tempfile.TemporaryDirectory() as tmpdir:
            kb = MedicalKnowledgeBase(
                db_path=str(Path(tmpdir) / "milvus_lite.db"),
                collection_name="medical_knowledge",
            )
            results = kb.search("头痛", top_k=1)

        self.assertEqual(results[0]["content"], "测试内容")
        self.assertGreaterEqual(client.load_collection.call_count, 2)
        client.load_collection.assert_any_call(collection_name="medical_knowledge")


if __name__ == "__main__":
    unittest.main()
