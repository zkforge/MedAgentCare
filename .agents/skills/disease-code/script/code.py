from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import failure, format_knowledge_results, search_medical_knowledge, success


def disease_code(disease: str, limit: int = 3):
    """Search ICD-10 disease code and classification information."""
    if not disease.strip():
        return failure("disease 不能为空", disease=disease)

    payload = search_medical_knowledge(
        query=f"{disease} ICD-10 编码 疾病分类",
        limit=limit,
        filter_type="disease_classification",
    )
    if not payload["success"]:
        return failure(
            "疾病编码检索失败，请确认 Milvus Lite、embedding 模型和数据导入状态。",
            disease=disease,
            cause=payload["error"],
        )

    answer = format_knowledge_results(
        query=disease,
        results=payload["results"],
        empty_message="未找到对应的 ICD-10 编码资料。",
    )
    return success(answer, disease=disease, **payload)
