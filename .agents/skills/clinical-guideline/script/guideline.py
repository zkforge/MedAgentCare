from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import failure, format_knowledge_results, search_medical_knowledge, success


def clinical_guideline(topic: str, limit: int = 3):
    """Search clinical guideline snippets from the medical knowledge base."""
    if not topic.strip():
        return failure("topic 不能为空", topic=topic)

    payload = search_medical_knowledge(
        query=f"{topic} 临床指南 诊疗规范 诊断标准 治疗建议",
        limit=limit,
        filter_type="clinical_guideline",
    )
    if not payload["success"]:
        return failure(
            "临床指南检索失败，请确认 Milvus Lite、embedding 模型和数据导入状态。",
            topic=topic,
            cause=payload["error"],
        )

    answer = format_knowledge_results(
        query=topic,
        results=payload["results"],
        empty_message="未找到对应的临床指南资料。",
    )
    return success(answer, topic=topic, **payload)
