"""
医疗回答结构化段落解析。

LLM 输出容易在标题、编号和项目符号上有轻微漂移，本模块把回答正文、
核心建议和免责声明拆成稳定字段，避免前端或 CLI 重复展示同一段内容。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


DEFAULT_MEDICAL_DISCLAIMER = (
    "以上信息仅供参考，不能替代专业医生的诊断和治疗。如有疑虑，请及时就医。"
)

_KNOWN_SECTION_NAMES = ("回答", "核心建议", "免责声明")
_SUGGESTION_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"[-*•]\s+|"
    r"\d{1,2}\s*[.)、]\s*|"
    r"[（(]\s*\d{1,2}\s*[）)]\s*|"
    r"[一二三四五六七八九十]+\s*[、.]\s*"
    r")(.+)$"
)


@dataclass(frozen=True)
class StructuredMedicalResponse:
    """结构化医疗回答字段。"""

    answer: str
    suggestions: List[str]
    disclaimer: str


def structure_medical_response(
    text: str,
    *,
    fallback_suggestions: Optional[Iterable[str]] = None,
    default_disclaimer: str = DEFAULT_MEDICAL_DISCLAIMER,
) -> StructuredMedicalResponse:
    """
    从 LLM 文本中提取结构化回答。

    Args:
        text: LLM 原始回答。
        fallback_suggestions: 未提取到建议时使用的兜底建议。
        default_disclaimer: 未提取到免责声明时使用的兜底免责声明。

    Returns:
        StructuredMedicalResponse，answer 已移除核心建议和免责声明段落。
    """
    raw_text = text or ""
    suggestions = extract_suggestions(raw_text)
    if not suggestions and fallback_suggestions is not None:
        suggestions = [
            item.strip()
            for item in fallback_suggestions
            if item and item.strip()
        ]

    disclaimer = extract_disclaimer(raw_text) or default_disclaimer
    answer = strip_structured_sections(raw_text)
    contains_structured_sections = any(
        _get_section(raw_text, section_name)
        for section_name in _KNOWN_SECTION_NAMES
    )

    return StructuredMedicalResponse(
        answer=answer or ("" if contains_structured_sections else raw_text.strip()),
        suggestions=suggestions[:5],
        disclaimer=disclaimer,
    )


def extract_suggestions(text: str) -> List[str]:
    """提取【核心建议】段落中的建议，兼容编号、项目符号和纯换行列表。"""
    section = _get_section(text, "核心建议")
    if not section:
        return []

    marked_items: List[str] = []
    current: List[str] = []
    plain_lines: List[str] = []

    for raw_line in section.splitlines():
        line = _clean_inline_text(raw_line)
        if not line or _is_heading_only(line):
            continue

        marker_match = _SUGGESTION_ITEM_RE.match(line)
        if marker_match:
            _append_candidate(marked_items, " ".join(current))
            current = [marker_match.group(1).strip()]
            continue

        if current:
            current.append(line)
        else:
            plain_lines.append(line)

    _append_candidate(marked_items, " ".join(current))
    candidates = marked_items or plain_lines
    return _dedupe(_clean_suggestion(item) for item in candidates)[:5]


def extract_disclaimer(text: str) -> str:
    """提取免责声明段落并压缩为单段文本。"""
    section = _get_section(text, "免责声明")
    if not section:
        return ""

    lines = [
        _clean_inline_text(line)
        for line in section.splitlines()
        if _clean_inline_text(line) and not _is_heading_only(line)
    ]
    return " ".join(lines).strip()


def strip_structured_sections(text: str) -> str:
    """
    移除核心建议和免责声明段落。

    如果存在【回答】标题，只移除标题本身，保留其正文；其它业务段落如
    【风险评估】、【诊断分析】会原样保留。
    """
    lines = (text or "").splitlines()
    output: List[str] = []
    skipping = False

    for raw_line in lines:
        heading = _parse_heading(raw_line)
        if heading:
            name, rest = heading
            if name in {"核心建议", "免责声明"}:
                skipping = True
                if rest:
                    continue
                continue

            skipping = False
            if name == "回答":
                if rest:
                    output.append(rest)
                continue

        if not skipping:
            output.append(raw_line)

    return _trim_blank_lines(output)


def _get_section(text: str, target_name: str) -> str:
    lines = (text or "").splitlines()
    collecting = False
    section_lines: List[str] = []

    for raw_line in lines:
        heading = _parse_heading(raw_line)
        if heading:
            name, rest = heading
            if collecting and name != target_name:
                break

            collecting = name == target_name
            if collecting and rest:
                section_lines.append(rest)
            continue

        if collecting:
            section_lines.append(raw_line)

    return _trim_blank_lines(section_lines)


def _parse_heading(line: str) -> Optional[Tuple[str, str]]:
    candidate = line.strip()
    if not candidate:
        return None

    candidate = re.sub(r"^#{1,6}\s*", "", candidate).strip()
    candidate = candidate.strip("*").strip()

    if candidate.startswith("【") and "】" in candidate:
        name, rest = candidate[1:].split("】", 1)
        return _canonical_section_name(name), rest.strip()

    for section_name in _KNOWN_SECTION_NAMES:
        if candidate == section_name:
            return section_name, ""
        for separator in ("：", ":"):
            prefix = f"{section_name}{separator}"
            if candidate.startswith(prefix):
                return section_name, candidate[len(prefix):].strip()

    return None


def _canonical_section_name(name: str) -> str:
    compact_name = re.sub(r"\s+", "", name).strip("：:")
    for section_name in _KNOWN_SECTION_NAMES:
        if section_name in compact_name:
            return section_name
    return compact_name


def _append_candidate(items: List[str], candidate: str) -> None:
    cleaned = _clean_suggestion(candidate)
    if cleaned:
        items.append(cleaned)


def _clean_suggestion(text: str) -> str:
    cleaned = _clean_inline_text(text)
    cleaned = _SUGGESTION_ITEM_RE.sub(r"\1", cleaned).strip()
    if not cleaned or _is_heading_only(cleaned):
        return ""
    if len(cleaned) <= 8 and cleaned.endswith(("：", ":")):
        return ""
    return cleaned


def _clean_inline_text(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _is_heading_only(text: str) -> bool:
    cleaned = _clean_inline_text(text)
    heading = _parse_heading(cleaned)
    if heading and not heading[1]:
        return True

    normalized = cleaned.strip("【】[]（）()：: ")
    return normalized in {"回答", "核心建议", "建议", "注意事项", "免责声明"}


def _dedupe(items: Iterable[str]) -> List[str]:
    results: List[str] = []
    seen = set()
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        key = re.sub(r"\s+", "", cleaned)
        if key in seen:
            continue
        seen.add(key)
        results.append(cleaned)
    return results


def _trim_blank_lines(lines: List[str]) -> str:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end]).strip()
