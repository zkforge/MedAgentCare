from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import failure, format_knowledge_results, search_medical_knowledge, success


def recommend_lifestyle(condition: str, limit: int = 3):
    """Return lifestyle guidance for a disease, symptom, or health condition."""
    if not condition.strip():
        return failure("condition 不能为空", condition=condition)

    payload = search_medical_knowledge(
        query=f"{condition} 生活方式 饮食 运动 用药 注意事项",
        limit=limit,
        filter_type="lifestyle",
    )
    if not payload["success"]:
        return failure(
            "生活方式建议检索失败，请确认 Milvus Lite、embedding 模型和数据导入状态。",
            condition=condition,
            cause=payload["error"],
        )

    answer = format_knowledge_results(
        query=condition,
        results=payload["results"],
        empty_message="未找到对应的生活方式建议资料。",
    )
    return success(answer, condition=condition, **payload)
