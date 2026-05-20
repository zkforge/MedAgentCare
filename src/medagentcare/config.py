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


# LLM API config (OpenAI-compatible endpoint)
LLM_CONFIG = {
    "api_key": _get_env("LLM_API_KEY") or _get_env("OPENAI_API_KEY"),
    "model_name": _get_env("LLM_MODEL_NAME", "doubao-seed-1-6-flash-250828"),
    "base_url": _get_env("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
    "temperature": _get_float_env("LLM_TEMPERATURE", 0.7),
    "max_tokens": _get_int_env("LLM_MAX_TOKENS", 8192),
}

# Mem0 API config (Long-term memory)
MEM0_CONFIG = {
    "api_key": _get_env("MEM0_API_KEY"),
}
