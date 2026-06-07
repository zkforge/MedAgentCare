"""Optional LangSmith tracing helpers."""
import os
from typing import Any, Callable, Dict

from loguru import logger


try:
    from langsmith import traceable as _langsmith_traceable
    from langsmith.wrappers import wrap_openai as _wrap_openai
except Exception as exc:  # pragma: no cover - defensive fallback
    _langsmith_traceable = None
    _wrap_openai = None
    logger.warning(f"LangSmith tracing unavailable: {exc}")


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def langsmith_enabled() -> bool:
    """Return whether LangSmith tracing should be active for this process."""
    return bool(
        _langsmith_traceable
        and _wrap_openai
        and _env_enabled("LANGSMITH_TRACING")
        and os.getenv("LANGSMITH_API_KEY", "").strip()
    )


def _compact_inputs(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Keep trace inputs useful without serializing large runtime objects."""
    if not isinstance(inputs, dict):
        return inputs

    compacted: Dict[str, Any] = {}
    for key, value in inputs.items():
        if key == "self":
            compacted[key] = value.__class__.__name__
        elif key == "agent":
            compacted["agent_id"] = getattr(value, "agent_id", value.__class__.__name__)
        elif key == "worker":
            compacted["worker_id"] = getattr(value, "agent_id", value.__class__.__name__)
        elif key == "shared_context":
            compacted[key] = {
                "session_id": getattr(value, "session_id", None),
                "completed_subtasks": len(getattr(value, "completed_subtasks", {}) or {}),
            }
        else:
            compacted[key] = value
    return compacted


def traceable(name: str, run_type: str = "chain", **kwargs: Any) -> Callable:
    """Decorate a function only when LangSmith tracing is configured."""
    def decorator(func: Callable) -> Callable:
        if not langsmith_enabled():
            return func

        decorator_kwargs = {
            "name": name,
            "run_type": run_type,
            "process_inputs": _compact_inputs,
            **kwargs,
        }
        return _langsmith_traceable(**decorator_kwargs)(func)

    return decorator


def wrap_openai_client(client: Any) -> Any:
    """Wrap an OpenAI-compatible SDK client when LangSmith tracing is enabled."""
    if not langsmith_enabled():
        return client

    try:
        return _wrap_openai(client, chat_name="MedAgentCare Chat Completions")
    except Exception as exc:  # pragma: no cover - tracing must not break runtime
        logger.warning(f"Failed to enable LangSmith OpenAI wrapper: {exc}")
        return client
