from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import ensure_project_path, failure, success


def _serialize_report(report):
    data = asdict(report)
    created_at = data.get("created_at")
    if isinstance(created_at, datetime):
        data["created_at"] = created_at.isoformat()
    return data


async def deep_research(question: str, use_web: bool = True, use_kb: bool = True):
    """Run the DeepResearch workflow and return a structured report."""
    if not question.strip():
        return failure("question 不能为空", question=question)

    ensure_project_path()
    try:
        from medagentcare.research.deep_research_workflow import deep_research as run_deep_research

        report = await run_deep_research(question=question, use_web=use_web, use_kb=use_kb)
        report_data = _serialize_report(report)
    except Exception as exc:
        return failure(
            "深度研究执行失败，请确认 LLM、网络搜索、Milvus/embedding 依赖已正确配置。",
            question=question,
            cause=str(exc),
        )

    answer = report_data.get("summary") or "深度研究完成，但未生成摘要。"
    return success(answer, question=question, report=report_data)
