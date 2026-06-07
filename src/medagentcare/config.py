"""
Runtime configuration.

Values are read from environment variables first so the project can run in
Docker or on a server without editing source files.
"""
import os
from pathlib import Path

from dotenv import load_dotenv


def _load_project_dotenv() -> None:
    """Load the project `.env` for local runs without overriding real env vars."""
    if os.getenv("MEDAGENTCARE_SKIP_DOTENV") == "1":
        return

    dotenv_path = os.getenv("MEDAGENTCARE_DOTENV_PATH")
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)
        return

    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env", override=False)


_load_project_dotenv()


def _get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_int_env(name: str, default: int) -> int:
    value = _get_env(name)
    if not value:
        return default
    return int(value)


def _get_float_env(name: str, default: float) -> float:
    value = _get_env(name)
    if not value:
        return default
    return float(value)


def _get_bool_env(name: str, default: bool) -> bool:
    value = _get_env(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _default_memory_dir() -> str:
    project_root = Path(__file__).resolve().parents[2]
    return str(project_root / ".medagentcare" / "memory")


def _default_sessions_dir() -> str:
    project_root = Path(__file__).resolve().parents[2]
    return str(project_root / ".medagentcare" / "sessions")


# LLM API config (OpenAI-compatible endpoint)
LLM_CONFIG = {
    "api_key": _get_env("LLM_API_KEY") or _get_env("OPENAI_API_KEY"),
    "model_name": _get_env("LLM_MODEL_NAME", "qwen3.6-plus"),
    "base_url": _get_env("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "temperature": _get_float_env("LLM_TEMPERATURE", 0.7),
    "max_tokens": _get_int_env("LLM_MAX_TOKENS", 8192),
}

# Mem0 API config (Long-term memory)
MEM0_CONFIG = {
    "api_key": _get_env("MEM0_API_KEY"),
}

# LangSmith tracing config. LangSmith SDK still reads these environment
# variables directly; this dict is for health reporting and local docs.
LANGSMITH_CONFIG = {
    "tracing": _get_bool_env("LANGSMITH_TRACING", False),
    "api_key": _get_env("LANGSMITH_API_KEY"),
    "project": _get_env("LANGSMITH_PROJECT", "medagentcare"),
    "endpoint": _get_env("LANGSMITH_ENDPOINT"),
}

# Personal health memory config. Env enables the backend capability; each
# request still has to opt in through the UI/API memory flag.
MEMORY_CONFIG = {
    "enabled": _get_bool_env("MEDAGENTCARE_MEMORY_ENABLED", True),
    "default_backend": _get_env("MEDAGENTCARE_MEMORY_BACKEND", "local") or "local",
    "memory_dir": _get_env("MEDAGENTCARE_MEMORY_DIR", _default_memory_dir()),
    "max_sessions": _get_int_env("MEDAGENTCARE_MEMORY_MAX_SESSIONS", 100),
    "user_id": "local_default",
}

# Local conversation store used by the frontend recent-session list and by the
# backend to restore recent visible context across API restarts.
SESSION_CONFIG = {
    "sessions_dir": _get_env("MEDAGENTCARE_SESSIONS_DIR", _default_sessions_dir()),
    "max_sessions": _get_int_env("MEDAGENTCARE_SESSION_MAX_SESSIONS", 100),
    "user_id": "local_default",
}
