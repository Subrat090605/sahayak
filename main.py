"""FastAPI application for Sahayak: voice-first citizen assistance platform.

Routes per docs/ARCHITECTURE.md:
- GET /health: Liveness health check
- POST /chat: Multi-agent conversational endpoint
- Static file serving at /
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents import generate_form_html, generate_ics, verify_document_image
from coordinator import SESSIONS, get_or_create_session, handle_message
from eligibility import load_schemes

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


class UploadDocResponse(BaseModel):
    doc_type: str = Field(..., description="Detected document type (aadhaar, land_record, bank_passbook, etc.)")
    matches_checklist: bool = Field(..., description="Whether document matches an expected checklist item")
    matched_doc_id: str | None = Field(default=None, description="Checklist item ID that was matched")
    readable: bool = Field(..., description="Whether the document text and name are readable")
    masked_id: str | None = Field(default=None, description="Masked ID showing only last 4 digits (e.g. XXXX-XXXX-1234)")
    notes: str = Field(..., description="Analysis notes or friendly guidance for citizen")


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


@app.post("/upload-doc", response_model=UploadDocResponse)
async def upload_doc_endpoint(
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
    scheme_id: str | None = Form(None),
    lang: str | None = Form("hi"),
) -> UploadDocResponse:
    """Document verification endpoint:
    Accepts an uploaded document image, processes it in memory only (never saved to disk),
    passes to the active vision model, verifies against scheme checklist,
    and returns document type, checklist match, readability, and masked ID.
    """
    t0 = time.time()
    try:
        # Read image bytes strictly in memory - NEVER saved to disk
        image_bytes = await file.read()
        mime_type = file.content_type or "image/jpeg"

        # Determine target scheme_id from session if not directly supplied
        resolved_scheme = scheme_id
        session = None
        if session_id:
            session = get_or_create_session(session_id, lang=lang or "hi")
            if not resolved_scheme:
                resolved_scheme = session.get("selected_scheme")
                if not resolved_scheme and session.get("matches"):
                    matches = session["matches"]
                    if len(matches) == 1:
                        resolved_scheme = matches[0].get("scheme_id")

        result = verify_document_image(
            image_bytes=image_bytes,
            mime_type=mime_type,
            scheme_id=resolved_scheme,
            lang=lang or "hi",
            filename=file.filename,
        )

        elapsed_ms = int((time.time() - t0) * 1000)

        # Update session trace if session exists
        if session is not None:
            if result.get("matches_checklist") and result.get("matched_doc_id"):
                verified = session.setdefault("verified_docs", [])
                if result["matched_doc_id"] not in verified:
                    verified.append(result["matched_doc_id"])
            trace_entry = {
                "agent": "document",
                "action": f"verified {result['doc_type']} (matches={result['matches_checklist']}, readable={result['readable']})",
                "ms": elapsed_ms,
            }
            session.setdefault("trace", []).append(trace_entry)
            session.setdefault("history", []).append(trace_entry)

        return UploadDocResponse(
            doc_type=result["doc_type"],
            matches_checklist=result["matches_checklist"],
            matched_doc_id=result.get("matched_doc_id"),
            readable=result["readable"],
            masked_id=result.get("masked_id"),
            notes=result["notes"],
        )
    except Exception as exc:
        logger.error("Error in /upload-doc endpoint: %s", exc, exc_info=True)
        user_lang = lang or "hi"
        fallback_notes = (
            "क्षमा करें, दस्तावेज़ अपलोड या सत्यापन में समस्या आई है। कृपया दोबारा प्रयास करें।"
            if user_lang == "hi"
            else "Sorry, an error occurred during document upload or verification. Please try again."
        )
        return UploadDocResponse(
            doc_type="unknown",
            matches_checklist=False,
            matched_doc_id=None,
            readable=False,
            masked_id=None,
            notes=fallback_notes,
        )



# ---------------------------------------------------------------------------
# Form Generation & Printing Endpoints
# ---------------------------------------------------------------------------


@app.get("/form/{scheme_id}", response_class=HTMLResponse)
def form_endpoint(
    scheme_id: str,
    session_id: str | None = None,
    lang: str | None = None,
) -> HTMLResponse:
    """Printable A4 HTML Form endpoint.

    Returns a single-page printable application draft including:
    - User's profile details pre-filled from active session
    - Scheme name (Hindi/English) and benefit description
    - Document checklist with verification tick status [?]
    - Official government portal link
    - Mandatory line: "Draft prepared by Sahayak. Submit on the official portal."
    - Proper A4 print CSS and clean Hindi font rendering via Noto Sans Devanagari.
    """
    profile: dict[str, Any] = {}
    verified_docs: list[str] = []
    preferred_lang = lang or "hi"

    if session_id and session_id in SESSIONS:
        session = SESSIONS[session_id]
        profile = session.get("profile", {})
        verified_docs = session.get("verified_docs", [])
        if not lang:
            preferred_lang = session.get("lang", "hi")

    schemes = load_schemes()
    html_content = generate_form_html(
        scheme_id=scheme_id,
        profile=profile,
        schemes=schemes,
        lang=preferred_lang,
        verified_docs=verified_docs,
        session_id=session_id,
    )
    return HTMLResponse(content=html_content, status_code=200)


@app.get("/form", response_class=HTMLResponse)
def form_query_endpoint(
    scheme_id: str | None = None,
    session_id: str | None = None,
    lang: str | None = None,
) -> HTMLResponse:
    """Alternative form endpoint accepting query parameters (e.g. /form?scheme_id=pm-kisan)."""
    target_scheme = scheme_id
    if session_id and session_id in SESSIONS and not target_scheme:
        session = SESSIONS[session_id]
        target_scheme = session.get("selected_scheme")
        if not target_scheme and session.get("matches"):
            eligible = [m["scheme_id"] for m in session["matches"] if m.get("status") == "eligible"]
            if eligible:
                target_scheme = eligible[0]

    if not target_scheme:
        schemes = load_schemes()
        target_scheme = schemes[0]["id"] if schemes else "pm-kisan"

    return form_endpoint(scheme_id=target_scheme, session_id=session_id, lang=lang)


# ---------------------------------------------------------------------------
# Calendar Reminders Endpoints (.ics)
# ---------------------------------------------------------------------------


@app.get("/reminders.ics")
def reminders_ics_endpoint(
    scheme_id: str | None = None,
    session_id: str | None = None,
    lang: str | None = None,
) -> Response:
    """Calendar reminders (.ics) endpoint.

    Follows P6.3:
    Returns an RFC 5545 iCalendar file with reminders at 3 days (collect docs),
    7 days (submit application), and 30 days (check status).
    Includes real deadline ONLY if schemes.json contains one; never invents deadlines.
    """
    target_scheme = scheme_id
    preferred_lang = lang or "hi"

    if session_id and session_id in SESSIONS:
        session = SESSIONS[session_id]
        if not target_scheme:
            target_scheme = session.get("selected_scheme")
            if not target_scheme and session.get("matches"):
                eligible = [m["scheme_id"] for m in session["matches"] if m.get("status") == "eligible"]
                if eligible:
                    target_scheme = eligible[0]
        if not lang:
            preferred_lang = session.get("lang", "hi")

    schemes = load_schemes()
    if not target_scheme:
        target_scheme = schemes[0]["id"] if schemes else "pm-kisan"

    ics_content = generate_ics(
        scheme_id=target_scheme,
        schemes=schemes,
        lang=preferred_lang,
        session_id=session_id,
    )

    filename = f"reminders_{target_scheme}.ics"
    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@app.get("/reminders/{scheme_id}.ics")
def reminders_scheme_alias(
    scheme_id: str,
    session_id: str | None = None,
    lang: str | None = None,
) -> Response:
    """Direct scheme alias for calendar file (e.g. /reminders/pm-kisan.ics)."""
    return reminders_ics_endpoint(scheme_id=scheme_id, session_id=session_id, lang=lang)


# ---------------------------------------------------------------------------
# Static Files (Mounted last so API routes take precedence)
# ---------------------------------------------------------------------------

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
