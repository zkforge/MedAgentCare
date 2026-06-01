"""Lightweight request-scoped trace events for SSE progress output."""
import asyncio
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional


TraceCallback = Callable[[Dict[str, Any]], Awaitable[None]]

_trace_callback: ContextVar[Optional[TraceCallback]] = ContextVar(
    "medagentcare_trace_callback",
    default=None,
)


def set_trace_callback(callback: Optional[TraceCallback]):
    """Bind a progress callback to the current async request context."""
    return _trace_callback.set(callback)


def reset_trace_callback(token) -> None:
    """Restore the previous request trace callback."""
    _trace_callback.reset(token)


def has_trace_callback() -> bool:
    return _trace_callback.get() is not None


def text_preview(value: Any, limit: int = 80) -> str:
    """Return a short, single-line preview that is safe for UI metadata."""
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


async def emit_trace_event(
    *,
    stage: str,
    title: str,
    detail: str = "",
    status: str = "running",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit one trace/progress event if the current request has a callback."""
    callback = _trace_callback.get()
    if callback is None:
        return

    payload = {
        "timestamp": datetime.now().isoformat(),
        "stage": stage,
        "title": title,
        "detail": detail,
        "status": status,
        "metadata": {
            "trace": True,
            **(metadata or {}),
        },
    }
    try:
        await callback(payload)
    except Exception:
        # Tracing must never break the medical consultation path.
        return


def emit_trace_event_nowait(
    *,
    stage: str,
    title: str,
    detail: str = "",
    status: str = "running",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Schedule a trace event from synchronous code when an event loop exists."""
    if not has_trace_callback():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        emit_trace_event(
            stage=stage,
            title=title,
            detail=detail,
            status=status,
            metadata=metadata,
        )
    )
