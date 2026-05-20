from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_helpers import ensure_project_path, failure, success


def search_history(session_id: str = "", limit: int = 10):
    """Search recent messages from the current short-term memory session."""
    if not session_id:
        return failure("缺少 session_id，无法检索当前会话历史。", session_id=session_id)

    ensure_project_path()
    try:
        from medagentcare.memory import ShortTermMemory

        memory = ShortTermMemory(storage_type="memory")
        messages = memory.get_recent_messages(session_id=session_id, limit=limit)
    except Exception as exc:
        return failure("短期记忆检索失败。", session_id=session_id, cause=str(exc))

    if not messages:
        return success("当前会话暂无可检索的历史记录。", session_id=session_id, total_messages=0, messages=[])

    lines = [f"当前会话最近 {len(messages)} 条记录："]
    for item in messages:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        lines.append(f"- {role}: {content[:240]}")

    return success(
        "\n".join(lines),
        session_id=session_id,
        total_messages=len(messages),
        messages=messages,
    )
