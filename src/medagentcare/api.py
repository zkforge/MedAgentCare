"""
FastAPI entrypoint for MedAgentCare.

The API layer is intentionally thin: it validates HTTP input, delegates the
medical consultation flow to the existing Swarm pipeline, and returns the raw
structured result for frontend or deployment integrations.
"""
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from medagentcare.config import LLM_CONFIG, MEM0_CONFIG


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
        from medagentcare.swarm import process_with_swarm

        return await process_with_swarm(
            question=request.question,
            context=request.context or None,
            enable_swarm=request.enable_swarm,
            session_id=request.session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"consultation failed: {exc}") from exc
