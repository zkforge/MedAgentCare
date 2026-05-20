from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import ensure_project_path, failure, success


def search_similar_cases(query: str, limit: int = 3):
    """Search similar historical sessions from long-term memory."""
    if not query.strip():
        return failure("query 不能为空", query=query)

    ensure_project_path()
    try:
        from memory import LongTermMemory

        memory = LongTermMemory()
        if not memory.enabled:
            return success(
                "长期记忆未启用，无法检索相似历史案例。请配置 MEM0_API_KEY 后重试。",
                query=query,
                enabled=False,
                total_found=0,
                results=[],
            )
        results = memory.search_similar_sessions(query=query, limit=limit)
    except Exception as exc:
        return failure("长期记忆检索失败。", query=query, cause=str(exc))

    if not results:
        return success("未找到相似历史案例。", query=query, enabled=True, total_found=0, results=[])

    lines = [f"找到 {len(results)} 条相似历史案例："]
    for index, item in enumerate(results, 1):
        score = item.get("score", 0)
        content = item.get("content", "")
        lines.append(f"{index}. 相似度 {score:.2f}: {content[:240]}")

    return success(
        "\n".join(lines),
        query=query,
        enabled=True,
        total_found=len(results),
        results=results,
    )
