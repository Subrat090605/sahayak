"""FastAPI application for Sahayak: voice-first citizen assistance platform.

Routes per docs/ARCHITECTURE.md:
- GET /health: Liveness health check
- POST /chat: Multi-agent conversational endpoint
- Static file serving at /
"""

from __future__ import annotations

import asyncio

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents import eligibility_agent, generate_form_html, generate_ics, verify_document_image
from coordinator import SESSIONS, get_or_create_session, handle_message
from eligibility import load_schemes
from llm import transcribe_audio

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


class TranscribeResponse(BaseModel):
    text: str = Field(..., description="Transcribed text from speech recording")
    status: str = Field(default="ok", description="'ok' or 'error'")
    error: str | None = Field(default=None, description="Error explanation if status is error")


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


class DemoLoadRequest(BaseModel):
    session_id: str | None = Field(default=None, description="Optional session UUID")
    lang: str | None = Field(default="hi", description="Preferred language ('hi' or 'en')")
    profile: dict[str, Any] | None = Field(default=None, description="Optional profile fields override")


class DemoLoadResponse(BaseModel):
    status: str = Field(default="ok", description="Status code")
    session_id: str = Field(..., description="Active session ID")
    profile: dict[str, Any] = Field(..., description="Loaded sample farmer profile")
    state: str = Field(..., description="Session state machine state")
    matches: list[dict[str, Any]] = Field(default_factory=list, description="Scheme matches")
    reply: str = Field(..., description="Introductory guidance text")
    trace: list[dict[str, Any]] = Field(default_factory=list, description="Trace entries")
    demo_steps: list[dict[str, Any]] = Field(default_factory=list, description="Automated demo playback steps")


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/demo/load", response_model=DemoLoadResponse)
def demo_load_endpoint(payload: DemoLoadRequest | None = None) -> DemoLoadResponse:
    """Demo Load Endpoint (per docs/ARCHITECTURE.md & P7.2).

    Loads the sample farmer profile (Unnao, UP, 2 acres, low income) into active session,
    evaluates scheme eligibility, and returns the profile, initial matches, and scripted steps.
    """
    req = payload or DemoLoadRequest()
    session_id = req.session_id or f"demo-{uuid.uuid4().hex[:8]}"
    preferred_lang = req.lang or "hi"

    session = get_or_create_session(session_id, lang=preferred_lang)

    sample_profile: dict[str, Any] = {
        "name": "रामेश कुमार (Ramesh Kumar)",
        "occupation": "farmer",
        "state": "Uttar Pradesh",
        "district": "Unnao",
        "land_acres": 2.0,
        "annual_income": 80000,
        "gender": "male",
        "age": 42,
    }
    if req.profile:
        sample_profile.update(req.profile)

    session["profile"] = sample_profile
    session["selected_scheme"] = "pm-kisan"
    session["state"] = "MATCH"
    session["lang"] = preferred_lang

    schemes = load_schemes()
    elig_res = eligibility_agent(
        profile=sample_profile,
        schemes=schemes,
        lang=preferred_lang,
    )
    session["matches"] = elig_res.get("matches", [])

    trace = [
        {
            "agent": "coordinator",
            "action": "loaded sample farmer profile (Unnao, 2 acres, income ₹80,000)",
            "ms": 12,
        },
        {
            "agent": "eligibility",
            "action": f"evaluated {len(schemes)} schemes: matched {sum(1 for m in session['matches'] if m.get('status') == 'eligible')} eligible",
            "ms": 25,
        },
    ]

    reply = (
        "नमस्ते रामेश जी! आपका किसान प्रोफाइल सफलतापूर्वक लोड हो गया है। आप पीएम-किसान सम्मान निधि (PM-KISAN) के लिए पात्र हैं।"
        if preferred_lang == "hi"
        else "Hello Ramesh! Your sample farmer profile is loaded. You are eligible for PM-KISAN (direct income support)."
    )

    demo_steps = [
        {
            "step": 1,
            "message_hi": "नमस्ते, मैं उन्नाव का किसान हूँ और मेरे पास 2 एकड़ ज़मीन है।",
            "message_en": "Hello, I am a farmer in Unnao with two acres of land.",
            "description": "Farmer intro (occupation & land)",
        },
        {
            "step": 2,
            "message_hi": "मेरी वार्षिक पारिवारिक आय लगभग 80,000 रुपये है।",
            "message_en": "My annual family income is around 80,000 rupees.",
            "description": "Farmer supplies missing income",
        },
        {
            "step": 3,
            "message_hi": "मुझे पीएम-किसान योजना के लिए कौन से दस्तावेज़ चाहिए?",
            "message_en": "What documents do I need for PM-KISAN?",
            "description": "Citizen asks for document checklist & PDF draft",
        },
    ]

    return DemoLoadResponse(
        status="ok",
        session_id=session_id,
        profile=sample_profile,
        state=session["state"],
        matches=session["matches"],
        reply=reply,
        trace=trace,
        demo_steps=demo_steps,
    )


@app.get("/demo/load", response_model=DemoLoadResponse)
def demo_load_get_endpoint(session_id: str | None = None, lang: str | None = "hi") -> DemoLoadResponse:
    """GET alias for /demo/load supporting browser address bar & query testing."""
    return demo_load_endpoint(DemoLoadRequest(session_id=session_id, lang=lang))


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
    except (TimeoutError, asyncio.TimeoutError) as exc:
        logger.error("Timeout in /chat endpoint: %s", exc)
        user_lang = payload.lang or "hi"
        fallback_msg = (
            "⏱️ अनुरोध का समय समाप्त हो गया (Request Timed Out)। कृपया नीचे लिखकर पुनः प्रयास करें।"
            if user_lang == "hi"
            else "⏱️ The request timed out. Please try typing your message again."
        )
        session = get_or_create_session(payload.session_id, lang=user_lang)
        return ChatResponse(
            reply=fallback_msg,
            lang=user_lang,
            state=session.get("state", "COLLECT_PROFILE"),
            matches=session.get("matches", []),
            trace=[{
                "agent": "coordinator",
                "action": f"friendly timeout error recovery: {type(exc).__name__}",
                "ms": 0,
            }],
        )
    except Exception as exc:
        logger.error("Error in /chat endpoint: %s", exc, exc_info=True)
        user_lang = payload.lang or "hi"
        err_str = str(exc).lower()
        is_timeout = "timeout" in err_str or "timed out" in err_str
        if is_timeout:
            fallback_msg = (
                "⏱️ अनुरोध का समय समाप्त हो गया (Request Timed Out)। कृपया नीचे लिखकर पुनः प्रयास करें।"
                if user_lang == "hi"
                else "⏱️ The request timed out. Please try typing your message again."
            )
            action_desc = f"friendly timeout error recovery: {type(exc).__name__}"
        else:
            fallback_msg = (
                "क्षमा करें, AI मॉडल या सेवा में अस्थायी समस्या आई है। कृपया अपना संदेश लिखकर दोबारा प्रयास करें।"
                if user_lang == "hi"
                else "Sorry, we encountered a temporary service issue. Please try typing your message again."
            )
            action_desc = f"friendly model error recovery: {type(exc).__name__}"

        session = get_or_create_session(payload.session_id, lang=user_lang)
        return ChatResponse(
            reply=fallback_msg,
            lang=user_lang,
            state=session.get("state", "COLLECT_PROFILE"),
            matches=session.get("matches", []),
            trace=[{
                "agent": "coordinator",
                "action": action_desc,
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


# ---------------------------------------------------------------------------
# Speech-to-Text Transcription Endpoint (Groq Whisper)
# ---------------------------------------------------------------------------


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_endpoint(
    file: UploadFile = File(..., description="Audio recording file (webm, wav, mp4, ogg)"),
    lang: str | None = Form(None, description="Optional language hint (hi or en)"),
) -> TranscribeResponse:
    """Accepts a short audio recording, sends it to Groq's speech-to-text model
    from the environment file (GROQ_STT_MODEL), and returns the transcribed text.
    """
    try:
        audio_bytes = await file.read()
        if not audio_bytes or len(audio_bytes) < 32:
            return TranscribeResponse(
                text="",
                status="error",
                error="Empty or invalid audio recording received.",
            )

        filename = file.filename or "recording.webm"
        mime_type = file.content_type or "audio/webm"
        lang_hint = lang if lang in {"hi", "en"} else None

        text = transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            mime_type=mime_type,
            language=lang_hint,
        )

        return TranscribeResponse(text=text, status="ok")
    except Exception as exc:
        logger.error("Error in /transcribe endpoint: %s", exc, exc_info=True)
        return TranscribeResponse(
            text="",
            status="error",
            error=str(exc),
        )


# Static Files (Mounted last so API routes take precedence)
# ---------------------------------------------------------------------------

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
