"""
FastAPI entrypoint for MedAgentCare.

The API layer validates HTTP input, delegates the medical consultation flow to
the existing Swarm pipeline, and exposes both regular JSON and SSE interfaces
for frontend or deployment integrations.
"""
import asyncio
import json
import os
import re
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from medagentcare.config import LLM_CONFIG, MEM0_CONFIG, MEMORY_CONFIG, SESSION_CONFIG
from medagentcare.memory import ConversationStore, LocalHealthMemory, LongTermMemory


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


app = FastAPI(
    title="MedAgentCare API",
    version="0.1.0",
    description="HTTP API for the MedAgentCare multi-agent medical assistant.",
)


def _parse_cors_origins() -> List[str]:
    """Read CORS origins from env, falling back to common local dev ports.

    Set ``MEDAGENTCARE_CORS_ORIGINS`` to a comma-separated list of origins
    (or ``*`` to allow any origin) when deploying the API behind a proxy
    that does not share the frontend domain.
    """
    raw = os.environ.get("MEDAGENTCARE_CORS_ORIGINS", "").strip()
    if not raw:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    if raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


_cors_origins = _parse_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


class ChatMemoryRequest(BaseModel):
    """Per-request long-term memory preference."""

    enabled: bool = Field(default=False, description="Whether this request may read/write long-term memory.")
    backend: str = Field(default="local", pattern="^(local|mem0)$", description="Long-term memory backend.")


class ChatRequest(BaseModel):
    """Request body for a medical consultation turn."""

    question: str = Field(..., min_length=1, description="User medical or health question.")
    context: Dict[str, Any] = Field(default_factory=dict, description="Optional structured context.")
    enable_swarm: bool = Field(default=True, description="Whether to allow multi-agent routing.")
    session_id: Optional[str] = Field(default=None, description="Optional conversation session id.")
    memory: Optional[ChatMemoryRequest] = Field(default=None, description="Optional long-term memory controls.")


class ProfileCandidate(BaseModel):
    """Candidate stable profile item generated from a confirmed session."""

    type: str = ""
    value: str = ""
    evidence: str = ""
    confidence: str = ""


class MemorySummaryPreview(BaseModel):
    """Structured memory summary preview produced before user confirmation."""

    title: str
    summary: str
    tags: List[str] = Field(default_factory=list)
    urgency: str = "unknown"
    timeline: str = ""
    care_recommendation: str = ""
    profile_candidates: List[ProfileCandidate] = Field(default_factory=list)


class MemorySummaryConfirmRequest(BaseModel):
    """Confirm a generated summary into the selected long-term backend."""

    backend: str = Field(default="local", pattern="^(local|mem0)$")
    summary: MemorySummaryPreview


class SessionCreateRequest(BaseModel):
    """Create a persisted visible conversation session."""

    session_id: Optional[str] = None
    title: str = "新的咨询"


def _local_memory() -> LocalHealthMemory:
    return LocalHealthMemory(
        MEMORY_CONFIG["memory_dir"],
        user_id=MEMORY_CONFIG["user_id"],
        max_sessions=MEMORY_CONFIG["max_sessions"],
    )


def _conversation_store() -> ConversationStore:
    return ConversationStore(
        SESSION_CONFIG["sessions_dir"],
        user_id=SESSION_CONFIG["user_id"],
        max_sessions=SESSION_CONFIG["max_sessions"],
    )


def _extract_json_object(text: str) -> Dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM did not return a JSON object")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM summary response must be a JSON object")
    return parsed


def _coerce_summary_text(value: Any) -> str:
    """Convert common LLM JSON type drift into a stable display string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            text = _coerce_summary_text(item)
            if text:
                parts.append(text)
        return "；".join(parts)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _coerce_summary_tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [tag for item in value if (tag := _coerce_summary_text(item))]
    if isinstance(value, str):
        parts = re.split(r"[,，、;；\s]+", value.strip())
        return [part for part in parts if part]
    return [_coerce_summary_text(value)]


def _coerce_confidence(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value >= 0.75:
            return "高"
        if value >= 0.4:
            return "中"
        return "低"
    return _coerce_summary_text(value)


def _normalize_memory_summary_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM summary JSON before Pydantic validation.

    The summary LLM is instructed to produce a strict schema, but compatible
    models may still return list recommendations or numeric confidence values.
    Normalize only these safe shape differences; missing content remains empty
    for the user to decide whether to confirm.
    """
    normalized = {
        "title": _coerce_summary_text(payload.get("title")) or "本次健康咨询",
        "summary": _coerce_summary_text(payload.get("summary")),
        "tags": _coerce_summary_tags(payload.get("tags")),
        "urgency": _coerce_summary_text(payload.get("urgency")) or "unknown",
        "timeline": _coerce_summary_text(payload.get("timeline")),
        "care_recommendation": _coerce_summary_text(payload.get("care_recommendation")),
        "profile_candidates": [],
    }

    candidates = payload.get("profile_candidates", [])
    if isinstance(candidates, dict):
        candidates = [candidates]
    if not isinstance(candidates, list):
        candidates = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        normalized["profile_candidates"].append(
            {
                "type": _coerce_summary_text(candidate.get("type")),
                "value": _coerce_summary_text(candidate.get("value")),
                "evidence": _coerce_summary_text(candidate.get("evidence")),
                "confidence": _coerce_confidence(candidate.get("confidence")),
            }
        )

    return normalized


def _sse_event(event: str, data: Dict[str, Any]) -> str:
    """Serialize one Server-Sent Events frame with JSON payload."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def _drain_progress_queue(progress_queue: asyncio.Queue[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect queued progress records without blocking the response."""
    records = []
    while True:
        try:
            records.append(progress_queue.get_nowait())
        except asyncio.QueueEmpty:
            return records


async def _run_chat_pipeline(
    request: ChatRequest,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Run the shared Swarm pipeline for JSON and SSE entrypoints."""
    from medagentcare.swarm import process_with_swarm

    context = dict(request.context or {})
    store = _conversation_store()
    recent_history = store.recent_history(request.session_id, limit=10)
    if recent_history and "recent_history" not in context:
        context["recent_history"] = recent_history
    interview_state = store.get_interview_state(request.session_id)
    if interview_state:
        context["_persisted_interview_state"] = interview_state

    return await process_with_swarm(
        question=request.question,
        context=context or None,
        enable_swarm=request.enable_swarm,
        session_id=request.session_id,
        progress_callback=progress_callback,
        memory=request.memory.model_dump() if request.memory else None,
    )


async def _stream_chat_events(
    request: ChatRequest,
    heartbeat_interval: float = 10.0,
) -> AsyncIterator[str]:
    """Stream lifecycle events while the existing consultation pipeline runs.

    SSE keeps the HTTP response active during slow multi-agent/LLM work. The
    pipeline emits high-level progress records for user-visible runtime state,
    then returns the final consultation result.
    """
    progress_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=1000)

    async def publish_progress(payload: Dict[str, Any]) -> None:
        try:
            progress_queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    task = asyncio.create_task(_run_chat_pipeline(request, publish_progress))
    yield _sse_event(
        "start",
        {
            "session_id": request.session_id,
            "enable_swarm": request.enable_swarm,
            "memory": request.memory.model_dump() if request.memory else {"enabled": False},
        },
    )

    progress_waiter: Optional[asyncio.Task[Dict[str, Any]]] = None
    try:
        heartbeat_count = 0
        progress_waiter = asyncio.create_task(progress_queue.get())

        while True:
            wait_targets = {task}
            if progress_waiter is not None:
                wait_targets.add(progress_waiter)

            done, _ = await asyncio.wait(
                wait_targets,
                timeout=heartbeat_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if done:
                if progress_waiter is not None and progress_waiter in done:
                    yield _sse_event("progress", progress_waiter.result())
                    for payload in _drain_progress_queue(progress_queue):
                        yield _sse_event("progress", payload)

                    if task.done():
                        progress_waiter = None
                    else:
                        progress_waiter = asyncio.create_task(progress_queue.get())

                if task in done:
                    break
                continue

            heartbeat_count += 1
            yield _sse_event("heartbeat", {"count": heartbeat_count})

        if progress_waiter is not None and not progress_waiter.done():
            progress_waiter.cancel()

        for payload in _drain_progress_queue(progress_queue):
            yield _sse_event("progress", payload)

        result = await task
        if result.get("session_id"):
            _conversation_store().append_turn(
                session_id=result["session_id"],
                question=request.question,
                result=result,
            )

        # 问诊模式：根据 status 发送不同的事件类型
        if result.get("status") == "need_more_info":
            # 追问事件：前端应显示追问并等待用户输入
            yield _sse_event(
                "interview_question",
                {
                    "question": result.get("answer", ""),
                    "interview_round": result.get("interview_round", 0),
                    "max_rounds": result.get("max_rounds", 5),
                    "covered_dimensions": result.get("covered_dimensions", []),
                    "remaining_dimensions": result.get("remaining_dimensions", []),
                    "session_id": result.get("session_id"),
                },
            )
        else:
            # 正常结果（含问诊完成后转诊断的结果）
            if result.get("status") == "interview_complete":
                yield _sse_event(
                    "interview_complete",
                    {
                        "summary": result.get("answer", ""),
                        "session_id": result.get("session_id"),
                    },
                )
            yield _sse_event("result", result)

        yield _sse_event("done", {"ok": True})
    except asyncio.CancelledError:
        task.cancel()
        raise
    except ValueError as exc:
        yield _sse_event("error", {"status_code": 400, "detail": str(exc)})
    except Exception as exc:
        yield _sse_event(
            "error",
            {
                "status_code": 500,
                "detail": f"consultation failed: {exc}",
            },
        )
    finally:
        if progress_waiter is not None and not progress_waiter.done():
            progress_waiter.cancel()


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Return deployment health and configuration readiness."""
    return {
        "status": "ok",
        "service": "medagentcare",
        "llm_configured": bool(LLM_CONFIG.get("api_key")),
        "mem0_configured": bool(MEM0_CONFIG.get("api_key")),
        "memory_enabled": bool(MEMORY_CONFIG.get("enabled")),
        "memory_default_backend": MEMORY_CONFIG.get("default_backend"),
    }


@app.get("/sessions")
async def list_sessions() -> Dict[str, Any]:
    """Return persisted visible conversation sessions without full messages."""
    return {"sessions": _conversation_store().list_sessions()}


@app.post("/sessions")
async def create_session(request: SessionCreateRequest) -> Dict[str, Any]:
    """Create a persisted visible conversation session."""
    return _conversation_store().create_session(session_id=request.session_id, title=request.title)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    """Return one persisted visible conversation session with messages."""
    try:
        return _conversation_store().get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> Dict[str, Any]:
    """Delete one visible conversation and its local raw/summary memory traces."""
    deleted = _conversation_store().delete_session(session_id)
    memory_deleted = _local_memory().delete_session(session_id)
    return {"session_id": session_id, "deleted": deleted, "memory_deleted": memory_deleted}


@app.delete("/sessions")
async def clear_sessions() -> Dict[str, Any]:
    """Delete all visible conversation sessions."""
    return {"deleted": _conversation_store().clear()}


@app.get("/memory/status")
async def memory_status() -> Dict[str, Any]:
    """Return local personal memory status and configured backend capability."""
    local_status = _local_memory().status()
    return {
        "enabled": bool(MEMORY_CONFIG.get("enabled")),
        "default_backend": MEMORY_CONFIG.get("default_backend"),
        "user_id": MEMORY_CONFIG["user_id"],
        "local": local_status,
        "mem0_configured": bool(MEM0_CONFIG.get("api_key")),
    }


@app.get("/memory/local")
async def memory_local() -> Dict[str, Any]:
    """Return local raw sessions and confirmed summary index."""
    return _local_memory().list_memory()


@app.delete("/memory/local/session/{session_id}")
async def delete_memory_session(session_id: str) -> Dict[str, Any]:
    """Delete one local raw session and its confirmed local summary if present."""
    deleted = _local_memory().delete_session(session_id)
    return {"session_id": session_id, "deleted": deleted}


@app.delete("/memory/local")
async def clear_local_memory() -> Dict[str, Any]:
    """Clear all local raw sessions and confirmed local summaries."""
    return _local_memory().clear()


@app.post("/memory/sessions/{session_id}/summary/generate")
async def generate_memory_summary(session_id: str) -> Dict[str, Any]:
    """Generate a structured memory summary preview from a saved raw session."""
    memory = _local_memory()
    try:
        raw = memory.get_raw_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from medagentcare.core import LLMClient

    prompt = (
        "请基于以下用户实际看到的医疗咨询内容生成个人健康记忆摘要。\n"
        "只输出一个 JSON 对象，不要输出 Markdown，不要添加 JSON 之外的说明。\n"
        "字段和类型必须严格符合以下 schema：\n"
        "{\n"
        '  "title": "string，10-30字短标题",\n'
        '  "summary": "string，一段话概括本次咨询中值得用户确认保存的健康信息",\n'
        '  "tags": ["string，关键词"],\n'
        '  "urgency": "unknown|low|medium|high|emergency",\n'
        '  "timeline": "string，症状或事件时间线，没有则为空字符串",\n'
        '  "care_recommendation": "string，合并成一段话；不要使用数组",\n'
        '  "profile_candidates": [\n'
        "    {\n"
        '      "type": "symptom|condition|medication|allergy|lifestyle|preference|other",\n'
        '      "value": "string",\n'
        '      "evidence": "string，来自本次咨询内容的依据",\n'
        '      "confidence": "high|medium|low，不要使用数字"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "所有字符串字段必须输出字符串；不要把字符串字段输出为数组、对象、数字或 null。\n"
        "如果某字段没有可靠信息，输出空字符串或空数组。\n\n"
        "注意：不要新增用户没有提到的病史、诊断、用药或检查结果。\n\n"
        f"用户问题：{raw.get('question', '')}\n\n"
        f"最终回答：{raw.get('final_response', '')}\n\n"
        f"核心建议：{json.dumps(raw.get('suggestions', []), ensure_ascii=False)}\n\n"
        f"免责声明：{raw.get('disclaimer', '')}"
    )
    try:
        text = await LLMClient().chat(
            [
                {
                    "role": "system",
                    "content": "你是医疗咨询系统的记忆摘要生成器，只生成供用户确认的结构化 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        preview = MemorySummaryPreview.model_validate(
            _normalize_memory_summary_payload(_extract_json_object(text))
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="摘要生成失败：模型返回格式不符合要求，请重试。") from exc

    return {"session_id": session_id, "summary": preview.model_dump()}


@app.post("/memory/sessions/{session_id}/summary/confirm")
async def confirm_memory_summary(session_id: str, request: MemorySummaryConfirmRequest) -> Dict[str, Any]:
    """Persist a generated memory summary after explicit user confirmation."""
    local_memory = _local_memory()
    try:
        raw = local_memory.get_raw_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    summary = request.summary.model_dump()
    external_memory_id = None
    if request.backend == "mem0":
        external_memory_id = LongTermMemory().add_session_summary(
            session_id=session_id,
            question=summary["title"],
            answer=summary["summary"],
            metadata={
                "type": "confirmed_health_memory",
                "tags": summary.get("tags", []),
                "raw_question": raw.get("question", ""),
            },
            user_id=MEMORY_CONFIG["user_id"],
        )
        if not external_memory_id:
            raise HTTPException(status_code=500, detail="Mem0 保存失败，可重试")

    try:
        entry = local_memory.confirm_summary(
            session_id=session_id,
            summary=summary,
            backend=request.backend,
            external_memory_id=external_memory_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"summary confirmation failed: {exc}") from exc

    return {"session_id": session_id, "backend": request.backend, "summary": entry}


@app.post("/chat")
async def chat(request: ChatRequest) -> Dict[str, Any]:
    """Run one consultation turn through the existing Swarm pipeline."""
    try:
        result = await _run_chat_pipeline(request)
        if result.get("session_id"):
            _conversation_store().append_turn(
                session_id=result["session_id"],
                question=request.question,
                result=result,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"consultation failed: {exc}") from exc


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Run one consultation turn and stream progress as Server-Sent Events."""
    return StreamingResponse(
        _stream_chat_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
