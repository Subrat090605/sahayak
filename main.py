"""FastAPI application for Sahayak: voice-first citizen assistance platform.

Routes per docs/ARCHITECTURE.md:
- GET /health: Liveness health check
- POST /chat: Multi-agent conversational endpoint
- Static file serving at /
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from coordinator import get_or_create_session, handle_message

# Load environment variables without exposing secrets
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sahayak.main")

app = FastAPI(
    title="Sahayak API",
    description="Voice-first multi-agent scheme discovery for Indian citizens",
)


# ---------------------------------------------------------------------------
# Pydantic Request & Response Models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, description="UUID session identifier")
    message: str = Field(..., description="User message or speech transcript")
    lang: str | None = Field(default="hi", description="Preferred language code ('hi' or 'en')")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="Agent reply text in user's language")
    lang: str = Field(..., description="Active language ('hi' or 'en')")
    state: str = Field(..., description="Current session state machine state")
    matches: list[dict[str, Any]] = Field(default_factory=list, description="Scheme evaluation results")
    trace: list[dict[str, Any]] = Field(default_factory=list, description="Execution trace entries")


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest) -> ChatResponse:
    """Multi-agent chat endpoint handling conversational flow and error recovery."""
    try:
        result = handle_message(
            session_id=payload.session_id,
            message=payload.message,
            lang=payload.lang,
        )
        return ChatResponse(
            reply=result["reply"],
            lang=result["lang"],
            state=result["state"],
            matches=result.get("matches", []),
            trace=result.get("trace", []),
        )
    except Exception as exc:
        logger.error("Error in /chat endpoint: %s", exc, exc_info=True)
        user_lang = payload.lang or "hi"
        fallback_msg = (
            "क्षमा करें, नेटवर्क या सेवा में अस्थायी समस्या आई है। कृपया अपना संदेश लिखकर दोबारा प्रयास करें।"
            if user_lang == "hi"
            else "Sorry, we encountered a temporary service issue. Please try typing your message again."
        )
        session = get_or_create_session(payload.session_id, lang=user_lang)
        return ChatResponse(
            reply=fallback_msg,
            lang=user_lang,
            state=session.get("state", "COLLECT_PROFILE"),
            matches=session.get("matches", []),
            trace=[{
                "agent": "coordinator",
                "action": f"friendly error recovery: {type(exc).__name__}",
                "ms": 0,
            }],
        )


# ---------------------------------------------------------------------------
# Static Files (Mounted last so API routes take precedence)
# ---------------------------------------------------------------------------

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
