"""本地个人健康记忆。

第一版只支持单用户 ``local_default``。raw 对话用于用户确认前的证据留存，
只有确认后的 summary 会进入 ``index.jsonl`` 并参与后续检索。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_USER_ID = "local_default"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_session_id(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip(".-")
    if not safe:
        raise ValueError("session_id is required")
    return safe[:160]


def _as_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    latin = set(re.findall(r"[a-z0-9]{2,}", lowered))
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", lowered)
    cjk_bigrams = {a + b for a, b in zip(cjk_chars, cjk_chars[1:])}
    return latin | cjk_bigrams | set(cjk_chars)


class LocalHealthMemory:
    """基于 Markdown + JSONL 的本地个人健康记忆。"""

    def __init__(self, base_dir: str | Path, user_id: str = DEFAULT_USER_ID, max_sessions: int = 100):
        self.base_dir = Path(base_dir).expanduser()
        self.user_id = DEFAULT_USER_ID if user_id != DEFAULT_USER_ID else user_id
        self.max_sessions = max_sessions
        self.user_dir = self.base_dir / "users" / self.user_id
        self.raw_dir = self.user_dir / "raw_sessions"
        self.summary_dir = self.user_dir / "session_summaries"
        self.index_path = self.user_dir / "index.jsonl"
        self.memory_md_path = self.user_dir / "MEMORY.md"
        self.profile_path = self.user_dir / "memory_summary.md"

    def ensure_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.summary_dir.mkdir(parents=True, exist_ok=True)
        self.user_dir.mkdir(parents=True, exist_ok=True)
        if not self.profile_path.exists():
            self.profile_path.write_text("# 个人健康稳定档案\n\n暂无已确认档案项。\n", encoding="utf-8")
        if not self.memory_md_path.exists():
            self._rewrite_memory_md([])

    def status(self) -> Dict[str, Any]:
        self.ensure_dirs()
        return {
            "enabled": True,
            "user_id": self.user_id,
            "memory_dir": str(self.user_dir),
            "raw_count": len(list(self.raw_dir.glob("*.json"))),
            "summary_count": len(self._read_index()),
            "max_sessions": self.max_sessions,
        }

    def save_raw_session(
        self,
        *,
        session_id: str,
        question: str,
        answer: str,
        suggestions: Optional[List[str]] = None,
        disclaimer: str = "",
        backend: str = "local",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.ensure_dirs()
        safe_id = _safe_session_id(session_id)
        path = self.raw_dir / f"{safe_id}.json"
        existing = self.get_raw_session(safe_id) if path.exists() else {}
        created_at = existing.get("created_at") or _utc_now()
        payload = {
            "session_id": safe_id,
            "user_id": self.user_id,
            "created_at": created_at,
            "updated_at": _utc_now(),
            "question": question,
            "final_response": answer,
            "suggestions": suggestions or [],
            "disclaimer": disclaimer,
            "backend": backend,
            "metadata": metadata or {},
            "confirmed_summary": existing.get("confirmed_summary"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def get_raw_session(self, session_id: str) -> Dict[str, Any]:
        safe_id = _safe_session_id(session_id)
        path = self.raw_dir / f"{safe_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"raw session not found: {safe_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_memory(self) -> Dict[str, Any]:
        self.ensure_dirs()
        raw_sessions = []
        for path in sorted(self.raw_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            raw_sessions.append({
                "session_id": raw.get("session_id"),
                "created_at": raw.get("created_at"),
                "updated_at": raw.get("updated_at"),
                "question": raw.get("question", "")[:120],
                "backend": raw.get("backend"),
                "has_confirmed_summary": bool(raw.get("confirmed_summary")),
            })
        return {
            "status": self.status(),
            "summaries": self._read_index(),
            "raw_sessions": raw_sessions,
        }

    def confirm_summary(
        self,
        *,
        session_id: str,
        summary: Dict[str, Any],
        backend: str = "local",
        external_memory_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.ensure_dirs()
        raw = self.get_raw_session(session_id)
        entry = {
            "session_id": raw["session_id"],
            "user_id": self.user_id,
            "created_at": raw.get("created_at"),
            "confirmed_at": _utc_now(),
            "backend": backend,
            "external_memory_id": external_memory_id,
            "title": str(summary.get("title", "")).strip() or "未命名健康记忆",
            "summary": str(summary.get("summary", "")).strip(),
            "tags": _as_list(summary.get("tags")),
            "urgency": str(summary.get("urgency", "")).strip() or "unknown",
            "timeline": str(summary.get("timeline", "")).strip(),
            "care_recommendation": str(summary.get("care_recommendation", "")).strip(),
            "profile_candidates": summary.get("profile_candidates") if isinstance(summary.get("profile_candidates"), list) else [],
        }
        if not entry["summary"]:
            raise ValueError("summary is required")

        if backend == "local":
            self._write_summary_markdown(entry)
            entries = [item for item in self._read_index() if item.get("session_id") != entry["session_id"]]
            entries.append(entry)
            entries.sort(key=lambda item: item.get("confirmed_at", ""), reverse=True)
            self._write_index(entries)
            self._rewrite_memory_md(entries)

        raw["confirmed_summary"] = {
            "backend": backend,
            "confirmed_at": entry["confirmed_at"],
            "title": entry["title"],
            "external_memory_id": external_memory_id,
        }
        self.raw_dir.joinpath(f"{entry['session_id']}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return entry

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []

        scored = []
        for entry in self._read_index():
            haystack = " ".join(
                [
                    str(entry.get("title", "")),
                    str(entry.get("summary", "")),
                    str(entry.get("timeline", "")),
                    str(entry.get("care_recommendation", "")),
                    " ".join(_as_list(entry.get("tags"))),
                ]
            )
            overlap = len(query_tokens & _tokens(haystack))
            if overlap <= 0:
                continue
            scored.append((overlap / max(len(query_tokens), 1), entry))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "memory_id": item.get("session_id"),
                "session_id": item.get("session_id"),
                "title": item.get("title"),
                "content": item.get("summary"),
                "summary": item.get("summary"),
                "tags": item.get("tags", []),
                "timestamp": item.get("confirmed_at") or item.get("created_at"),
                "score": round(score, 4),
                "metadata": {
                    "backend": item.get("backend"),
                    "timeline": item.get("timeline"),
                    "urgency": item.get("urgency"),
                },
            }
            for score, item in scored[:limit]
        ]

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        safe_id = _safe_session_id(session_id)
        deleted = {"raw": False, "summary": False}
        raw_path = self.raw_dir / f"{safe_id}.json"
        summary_path = self.summary_dir / f"{safe_id}.md"
        if raw_path.exists():
            raw_path.unlink()
            deleted["raw"] = True
        if summary_path.exists():
            summary_path.unlink()
            deleted["summary"] = True

        entries = [entry for entry in self._read_index() if entry.get("session_id") != safe_id]
        self._write_index(entries)
        self._rewrite_memory_md(entries)
        return deleted

    def clear(self) -> Dict[str, Any]:
        self.ensure_dirs()
        raw_deleted = self._unlink_all(self.raw_dir.glob("*.json"))
        summary_deleted = self._unlink_all(self.summary_dir.glob("*.md"))
        self._write_index([])
        self._rewrite_memory_md([])
        return {"raw_deleted": raw_deleted, "summary_deleted": summary_deleted}

    def _read_index(self) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        entries = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def _write_index(self, entries: Iterable[Dict[str, Any]]) -> None:
        self.ensure_dirs()
        lines = [json.dumps(entry, ensure_ascii=False, separators=(",", ":")) for entry in entries]
        self.index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _write_summary_markdown(self, entry: Dict[str, Any]) -> None:
        tags = "、".join(_as_list(entry.get("tags"))) or "无"
        profile_candidates = entry.get("profile_candidates") or []
        candidates = "\n".join(
            f"- {item.get('type', 'unknown')}: {item.get('value', '')}（证据：{item.get('evidence', '')}）"
            for item in profile_candidates
            if isinstance(item, dict)
        )
        if not candidates:
            candidates = "- 无"
        content = (
            f"# {entry['title']}\n\n"
            f"- Session: `{entry['session_id']}`\n"
            f"- 时间: {entry.get('confirmed_at') or entry.get('created_at')}\n"
            f"- 标签: {tags}\n"
            f"- 紧急程度: {entry.get('urgency')}\n"
            f"- 时间线: {entry.get('timeline') or '未记录'}\n\n"
            f"## 摘要\n\n{entry['summary']}\n\n"
            f"## 建议\n\n{entry.get('care_recommendation') or '未记录'}\n\n"
            f"## 稳定档案候选\n\n{candidates}\n"
        )
        self.summary_dir.joinpath(f"{entry['session_id']}.md").write_text(content, encoding="utf-8")

    def _rewrite_memory_md(self, entries: Iterable[Dict[str, Any]]) -> None:
        lines = ["# 本地健康记忆索引", ""]
        entries = list(entries)
        if not entries:
            lines.append("暂无已确认会话摘要。")
        else:
            for entry in entries:
                tags = "、".join(_as_list(entry.get("tags"))) or "无标签"
                lines.append(
                    f"- `{entry.get('session_id')}` {entry.get('confirmed_at')}: "
                    f"**{entry.get('title')}** [{tags}]"
                )
        lines.append("")
        self.memory_md_path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _unlink_all(paths: Iterable[Path]) -> int:
        count = 0
        for path in list(paths):
            path.unlink()
            count += 1
        return count
