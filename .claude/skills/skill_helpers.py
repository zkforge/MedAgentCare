"""Shared helpers for local MedAgentCare skill scripts."""
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional


def project_root() -> Path:
    """Return the repository root from `.claude/skills/skill_helpers.py`."""
    return Path(__file__).resolve().parents[2]


def ensure_project_path() -> None:
    """Allow skill scripts loaded by file path to import project modules."""
    src_path = str(project_root() / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def success(answer: str, **payload: Any) -> Dict[str, Any]:
    data = {"success": True, "answer": answer}
    data.update(payload)
    return data


def failure(error: str, **payload: Any) -> Dict[str, Any]:
    data = {"success": False, "answer": error, "error": error}
    data.update(payload)
    return data


def search_medical_knowledge(
    query: str,
    limit: int = 5,
    filter_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Search the Milvus-backed medical knowledge base with structured fallback."""
    ensure_project_path()
    try:
        from medagentcare.knowledge.milvus_kb import MedicalKnowledgeBase

        kb = MedicalKnowledgeBase()
        results = kb.search(query=query, top_k=limit, filter_type=filter_type)
        return {
            "success": True,
            "query": query,
            "filter_type": filter_type,
            "total_found": len(results),
            "results": results,
        }
    except Exception as exc:
        return {
            "success": False,
            "query": query,
            "filter_type": filter_type,
            "total_found": 0,
            "results": [],
            "error": str(exc),
        }


def format_knowledge_results(query: str, results: List[Dict[str, Any]], empty_message: str) -> str:
    if not results:
        return empty_message

    lines = [f"查询：{query}", f"找到 {len(results)} 条相关资料："]
    for index, item in enumerate(results, 1):
        metadata = item.get("metadata", {})
        disease = metadata.get("disease") or metadata.get("title") or metadata.get("filename") or "医学资料"
        source = metadata.get("source", "医学知识库")
        score = item.get("score", 0)
        content = item.get("content", "").strip().replace("\n", " ")
        lines.append(f"{index}. {disease}（来源：{source}，相关度：{score:.2f}）")
        if content:
            lines.append(f"   {content[:240]}")
    return "\n".join(lines)


def split_terms(text: str) -> List[str]:
    separators = [",", "，", "、", ";", "；", "\n"]
    values = [text]
    for separator in separators:
        next_values = []
        for value in values:
            next_values.extend(value.split(separator))
        values = next_values
    return [value.strip() for value in values if value.strip()]
