"""
FastAPI entrypoint for MedAgentCare.

The API layer is intentionally thin: it validates HTTP input, delegates the
medical consultation flow to the existing Swarm pipeline, and returns the raw
structured result for frontend or deployment integrations.
"""
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import LLM_CONFIG, MEM0_CONFIG


app = FastAPI(
    title="MedAgentCare API",
    version="0.1.0",
    description="HTTP API for the MedAgentCare multi-agent medical assistant.",
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
        from swarm import process_with_swarm

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
