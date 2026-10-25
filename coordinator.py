"""Coordinator for Sahayak: in-memory session management, state machine, and trace builder.

Follows docs/ARCHITECTURE.md:
State machine: COLLECT_PROFILE -> MATCH -> DOCUMENTS -> FORM -> REMINDERS -> DONE
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from agents import eligibility_agent, profile_agent
from eligibility import load_schemes

logger = logging.getLogger("sahayak.coordinator")

# In-memory session store (no database, per ARCHITECTURE.md)
SESSIONS: dict[str, dict[str, Any]] = {}

RESTART_KEYWORDS = {
    "start over",
    "reset",
    "start again",
    "restart",
    "clear",
    "शुरू से",
    "फिर से",
    "रीसेट",
    "नए सिरे से",
}


def get_or_create_session(session_id: str | None = None, lang: str = "hi") -> dict[str, Any]:
    """Retrieve an existing session or initialize a fresh one."""
    if not session_id or session_id not in SESSIONS:
        new_id = session_id or str(uuid.uuid4())
        SESSIONS[new_id] = {
            "session_id": new_id,
            "lang": lang,
            "state": "COLLECT_PROFILE",
            "profile": {},
            "missing": [],
            "matches": [],
            "selected_scheme": None,
            "history": [],
        }
        return SESSIONS[new_id]
    return SESSIONS[session_id]


def reset_session(session_id: str, lang: str = "hi") -> dict[str, Any]:
    """Reset session state and profile to initial empty state."""
    SESSIONS[session_id] = {
        "session_id": session_id,
        "lang": lang,
        "state": "COLLECT_PROFILE",
        "profile": {},
        "missing": [],
        "matches": [],
        "selected_scheme": None,
        "history": [],
    }
    return SESSIONS[session_id]


def is_start_over(message: str) -> bool:
    """Check if the user requested a fresh session start."""
    clean = message.strip().lower()
    return clean in RESTART_KEYWORDS or any(kw in clean for kw in ["start over", "शुरू से"])


def handle_message(
    session_id: str | None,
    message: str,
    lang: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Coordinate multi-agent processing for an incoming message.

    Returns:
        dict:
            "reply": str,
            "lang": str,
            "state": str,
            "matches": list[dict],
            "trace": list[dict[str, Any]]  # [{"agent": ..., "action": ..., "ms": ...}]
    """
    initial_lang = lang or "hi"
    session = get_or_create_session(session_id, lang=initial_lang)
    trace: list[dict[str, Any]] = []

    # 1. Handle "start over" phrase
    if is_start_over(message):
        t0 = time.perf_counter()
        reset_session(session["session_id"], lang=session["lang"])
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        trace.append({
            "agent": "coordinator",
            "action": "session reset to initial state",
            "ms": elapsed_ms,
        })
        current_lang = session["lang"]
        reply = (
            "नमस्ते! हमने बातचीत को नए सिरे से शुरू कर दिया है। कृपया अपने बारे में बताएं (जैसे: आप क्या काम करते हैं और आपके पास कितनी ज़मीन है)।"
            if current_lang == "hi"
            else "Session reset. Please tell me about yourself (for example, your occupation and whether you own land)."
        )
        return {
            "reply": reply,
            "lang": current_lang,
            "state": "COLLECT_PROFILE",
            "matches": [],
            "trace": trace,
        }

    schemes = load_schemes()
    current_state = session["state"]

    # 2. State: COLLECT_PROFILE or general profile updates
    if current_state in {"COLLECT_PROFILE", "MATCH"}:
        # Step A: Profile Agent extracts fields
        t_prof = time.perf_counter()
        prof_res = profile_agent(
            message=message,
            existing_profile=session["profile"],
            provider=provider,
        )
        elapsed_prof_ms = int((time.perf_counter() - t_prof) * 1000)

        newly_extracted = prof_res.get("extracted", {})
        session["profile"] = prof_res.get("profile", session["profile"])

        # Update language if provided in payload or newly detected
        if lang:
            session["lang"] = lang
        elif prof_res.get("lang"):
            session["lang"] = prof_res["lang"]

        action_desc = (
            f"extracted {len(newly_extracted)} field(s): {', '.join(newly_extracted.keys())}"
            if newly_extracted
            else "analyzed message, no new fields"
        )
        trace.append({
            "agent": "profile",
            "action": action_desc,
            "ms": elapsed_prof_ms,
        })

        # Step B: Eligibility Agent checks missing fields & evaluates schemes
        t_elig = time.perf_counter()
        elig_res = eligibility_agent(
            profile=session["profile"],
            schemes=schemes,
            lang=session["lang"],
            provider=provider,
        )
        elapsed_elig_ms = int((time.perf_counter() - t_elig) * 1000)

        session["missing"] = elig_res.get("missing_fields", [])
        session["matches"] = elig_res.get("matches", [])

        if elig_res.get("needs_follow_up"):
            session["state"] = "COLLECT_PROFILE"
            trace.append({
                "agent": "eligibility",
                "action": f"asking for missing field: {elig_res.get('missing_field')}",
                "ms": elapsed_elig_ms,
            })
            reply = elig_res["reply"]
        else:
            session["state"] = "MATCH"
            eligible_count = sum(1 for m in session["matches"] if m.get("status") == "eligible")
            trace.append({
                "agent": "eligibility",
                "action": f"matched {eligible_count} scheme(s)",
                "ms": elapsed_elig_ms,
            })
            reply = elig_res["reply"]

    else:
        # Default fallback for advanced states (DOCUMENTS, FORM, REMINDERS)
        reply = "State handling in progress."

    session["history"].append({
        "user": message,
        "bot": reply,
    })

    return {
        "reply": reply,
        "lang": session["lang"],
        "state": session["state"],
        "matches": session["matches"],
        "trace": trace,
    }
