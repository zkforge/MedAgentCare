from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import failure, format_knowledge_results, search_medical_knowledge, success


def search_knowledge(query: str, limit: int = 5):
    """Search the local medical knowledge base."""
    if not query.strip():
        return failure("query 不能为空", query=query)

    payload = search_medical_knowledge(query=query, limit=limit)
    if not payload["success"]:
        return failure(
            "医学知识库检索失败，请确认 Milvus Lite、embedding 模型和数据导入状态。",
            query=query,
            cause=payload["error"],
        )

    answer = format_knowledge_results(
        query=query,
        results=payload["results"],
        empty_message="未在医学知识库中找到相关资料。",
    )
    return success(answer, **payload)
