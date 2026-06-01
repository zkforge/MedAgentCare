"""Request-scoped long-term memory controls."""
from contextvars import ContextVar, Token
from typing import Any, Dict


_memory_request: ContextVar[Dict[str, Any]] = ContextVar(
    "medagentcare_memory_request",
    default={
        "requested_enabled": False,
        "effective_enabled": False,
        "backend": "local",
        "disabled_reason": "request_disabled",
        "user_id": "local_default",
    },
)


def set_request_memory(state: Dict[str, Any]) -> Token[Dict[str, Any]]:
    """Bind effective long-term memory controls to the current request."""
    return _memory_request.set(dict(state))


def reset_request_memory(token: Token[Dict[str, Any]]) -> None:
    """Restore the previous request memory controls."""
    _memory_request.reset(token)


def get_request_memory() -> Dict[str, Any]:
    """Return current request-level memory controls."""
    return dict(_memory_request.get())
