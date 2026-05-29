"""
FastAPI entrypoint for MedAgentCare.

The API layer validates HTTP input, delegates the medical consultation flow to
the existing Swarm pipeline, and exposes both regular JSON and SSE interfaces
for frontend or deployment integrations.
"""
import asyncio
import json
import os
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from medagentcare.config import LLM_CONFIG, MEM0_CONFIG


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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    """Request body for a medical consultation turn."""

    question: str = Field(..., min_length=1, description="User medical or health question.")
    context: Dict[str, Any] = Field(default_factory=dict, description="Optional structured context.")
    enable_swarm: bool = Field(default=True, description="Whether to allow multi-agent routing.")
    session_id: Optional[str] = Field(default=None, description="Optional conversation session id.")


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

    return await process_with_swarm(
        question=request.question,
        context=request.context or None,
        enable_swarm=request.enable_swarm,
        session_id=request.session_id,
        progress_callback=progress_callback,
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
    progress_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=200)

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
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> Dict[str, Any]:
    """Run one consultation turn through the existing Swarm pipeline."""
    try:
        return await _run_chat_pipeline(request)
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
