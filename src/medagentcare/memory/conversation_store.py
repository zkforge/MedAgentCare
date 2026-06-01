"""本地会话存储。

该存储用于前端“最近会话”和后端短期上下文恢复，只保存用户可见对话。
长期健康记忆仍由 LocalHealthMemory/Mem0 的确认式流程负责。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_USER_ID = "local_default"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    if not safe:
        raise ValueError("session_id is required")
    return safe[:160]


def _message_id(prefix: str = "message") -> str:
    return f"{prefix}-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{uuid.uuid4().hex[:8]}"


def _first_line_title(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return "新的咨询"
    return normalized[:30] + ("..." if len(normalized) > 30 else "")


class ConversationStore:
    """JSON 文件形式的单用户会话存储。"""

    def __init__(self, base_dir: str | Path, user_id: str = DEFAULT_USER_ID, max_sessions: int = 100):
        self.base_dir = Path(base_dir).expanduser()
        self.user_id = DEFAULT_USER_ID if user_id != DEFAULT_USER_ID else user_id
        self.max_sessions = max_sessions
        self.user_dir = self.base_dir / "users" / self.user_id

    def ensure_dirs(self) -> None:
        self.user_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, session_id: Optional[str] = None, title: str = "新的咨询") -> Dict[str, Any]:
        self.ensure_dirs()
        safe_id = _safe_id(session_id) if session_id else f"session-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{uuid.uuid4().hex[:8]}"
        path = self._path(safe_id)
        now = _utc_now()
        if path.exists():
            return self.get_session(safe_id)
        session = {
            "id": safe_id,
            "title": title or "新的咨询",
            "createdAt": now,
            "updatedAt": now,
            "messages": [],
            "interview_state": None,
        }
        self._write(session)
        return self._public_session(session)

    def list_sessions(self) -> List[Dict[str, Any]]:
        self.ensure_dirs()
        sessions = []
        for path in self.user_dir.glob("*.json"):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            public = self._public_session(session)
            public["messages"] = []
            sessions.append(public)
        sessions.sort(key=lambda item: item.get("updatedAt", ""), reverse=True)
        return sessions

    def get_session(self, session_id: str) -> Dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        return self._public_session(json.loads(path.read_text(encoding="utf-8")))

    def append_turn(self, *, session_id: str, question: str, result: Dict[str, Any]) -> Dict[str, Any]:
        session = self._load_or_create(session_id)
        now = _utc_now()
        messages = session.setdefault("messages", [])
        messages.append({
            "id": _message_id("message"),
            "role": "user",
            "content": question,
            "createdAt": now,
        })
        assistant_response = self._visible_response(result)
        messages.append({
            "id": _message_id("message"),
            "role": "assistant",
            "content": str(result.get("answer", "")),
            "createdAt": now,
            "isStreaming": False,
            "progressEvents": [],
            "progressStatus": "已完成",
            "response": assistant_response,
        })
        if not session.get("messages") or session.get("title") == "新的咨询":
            session["title"] = _first_line_title(question)
        session["updatedAt"] = now
        if isinstance(result.get("interview_state"), dict):
            session["interview_state"] = result["interview_state"]
        elif result.get("status") != "need_more_info":
            session["interview_state"] = None
        self._write(session)
        return self._public_session(session)

    def recent_history(self, session_id: Optional[str], limit: int = 10) -> List[Dict[str, str]]:
        if not session_id:
            return []
        try:
            session = self.get_session(session_id)
        except FileNotFoundError:
            return []
        history = []
        for message in session.get("messages", []):
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                history.append({"role": role, "content": content})
        return history[-limit:]

    def get_interview_state(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        try:
            path = self._path(session_id)
            if not path.exists():
                return None
            session = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        state = session.get("interview_state")
        return state if isinstance(state, dict) else None

    def delete_session(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def clear(self) -> int:
        self.ensure_dirs()
        return self._unlink_all(self.user_dir.glob("*.json"))

    def _path(self, session_id: str) -> Path:
        return self.user_dir / f"{_safe_id(session_id)}.json"

    def _load_or_create(self, session_id: str) -> Dict[str, Any]:
        self.ensure_dirs()
        path = self._path(session_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        created = self.create_session(session_id=session_id)
        return json.loads(self._path(created["id"]).read_text(encoding="utf-8"))

    def _write(self, session: Dict[str, Any]) -> None:
        self.ensure_dirs()
        self._path(session["id"]).write_text(
            json.dumps(session, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _public_session(session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": session.get("id"),
            "title": session.get("title", "新的咨询"),
            "createdAt": session.get("createdAt"),
            "updatedAt": session.get("updatedAt"),
            "messages": session.get("messages", []),
        }

    @staticmethod
    def _visible_response(result: Dict[str, Any]) -> Dict[str, Any]:
        response = dict(result)
        response.pop("progress_events", None)
        response.pop("interview_state", None)
        return response

    @staticmethod
    def _unlink_all(paths: Iterable[Path]) -> int:
        count = 0
        for path in list(paths):
            path.unlink()
            count += 1
        return count
