"""Coordinator for Sahayak: in-memory session management, state machine, and trace builder.

Follows docs/ARCHITECTURE.md:
State machine: COLLECT_PROFILE -> MATCH -> DOCUMENTS -> FORM -> REMINDERS -> DONE
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from agents import document_agent, eligibility_agent, followup_agent, form_agent, profile_agent
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
            "verified_docs": [],
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
        "verified_docs": [],
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

    # Check if user expresses document or form intent or scheme selection
    doc_keywords = ["document", "checklist", "कहाँ", "दस्तावेज़", "दस्तावेज", "कागज़", "कागज", "कागजात"]
    form_keywords = [
        "form", "apply", "draft", "print", "download",
        "आवेदन", "फ़ॉर्म", "फार्म", "ड्राफ्ट", "प्रिंट", "डाउनलोड", "भरना", "भरें"
    ]
    is_doc_intent = any(w in message.lower() for w in doc_keywords)
    is_form_intent = any(w in message.lower() for w in form_keywords)
    reminder_keywords = [
        "reminder", "reminders", "calendar", "ics", "schedule", "followup", "follow-up",
        "\u092f\u093e\u0926", "\u0930\u093f\u092e\u093e\u0907\u0902\u0921\u0930", "\u0915\u0948\u0932\u0947\u0902\u0921\u0930", "\u0924\u093e\u0930\u0940\u0916", "\u0924\u093e\u0930\u0940\u0916\u0947\u0902", "\u0924\u093f\u0925\u093f", "\u0938\u092e\u092f"
    ]
    is_reminder_intent = any(w in message.lower() for w in reminder_keywords)

    matched_scheme_id = None
    for s in schemes:
        s_id = s["id"]
        s_name_en = s.get("name_en", "").lower()
        s_name_hi = s.get("name_hi", "")
        short_name_en = s_name_en.split("(")[0].strip() if s_name_en else ""
        short_name_hi = s_name_hi.split("(")[0].strip() if s_name_hi else ""

        if (
            s_id in message.lower()
            or (s_name_en and s_name_en in message.lower())
            or (short_name_en and short_name_en in message.lower())
            or (s_name_hi and s_name_hi in message)
            or (short_name_hi and short_name_hi in message)
        ):
            matched_scheme_id = s_id
            break

    # 2. State: REMINDERS handling (user asks for reminders or calendar)
    if is_reminder_intent or (current_state == "REMINDERS" and not is_doc_intent and not is_form_intent):
        target_scheme = matched_scheme_id or session.get("selected_scheme")
        if not target_scheme:
            eligible = [m["scheme_id"] for m in session.get("matches", []) if m.get("status") == "eligible"]
            if eligible:
                target_scheme = eligible[0]
            elif schemes:
                target_scheme = schemes[0]["id"]

        session["selected_scheme"] = target_scheme
        session["state"] = "REMINDERS"

        t_rem = time.perf_counter()
        rem_res = followup_agent(
            scheme_id=target_scheme,
            schemes=schemes,
            lang=session["lang"],
            session_id=session.get("session_id"),
        )
        elapsed_rem_ms = int((time.perf_counter() - t_rem) * 1000)

        trace.append({
            "agent": "followup",
            "action": f"generated reminders for {target_scheme} (3d, 7d, 30d)",
            "ms": elapsed_rem_ms,
        })
        reply = rem_res["reply"]

    # 3. State: FORM handling (user asks for form or applies)
    elif is_form_intent or (current_state == "FORM" and not is_doc_intent):
        target_scheme = matched_scheme_id or session.get("selected_scheme")
        if not target_scheme:
            eligible = [m["scheme_id"] for m in session.get("matches", []) if m.get("status") == "eligible"]
            if eligible:
                target_scheme = eligible[0]
            elif schemes:
                target_scheme = schemes[0]["id"]

        session["selected_scheme"] = target_scheme
        session["state"] = "FORM"

        t_form = time.perf_counter()
        form_res = form_agent(
            scheme_id=target_scheme,
            profile=session.get("profile", {}),
            schemes=schemes,
            lang=session["lang"],
            verified_docs=session.get("verified_docs", []),
            session_id=session.get("session_id"),
        )
        elapsed_form_ms = int((time.perf_counter() - t_form) * 1000)

        trace.append({
            "agent": "form",
            "action": f"generated draft application for {target_scheme}",
            "ms": elapsed_form_ms,
        })
        reply = form_res["reply"]

    # 3. State: DOCUMENTS or transition to DOCUMENTS
    elif current_state == "DOCUMENTS" or is_doc_intent or (current_state == "MATCH" and matched_scheme_id):
        target_scheme = matched_scheme_id or session.get("selected_scheme")
        if not target_scheme:
            eligible = [m["scheme_id"] for m in session.get("matches", []) if m.get("status") == "eligible"]
            if eligible:
                target_scheme = eligible[0]
            elif schemes:
                target_scheme = schemes[0]["id"]

        session["selected_scheme"] = target_scheme
        session["state"] = "DOCUMENTS"

        t_doc = time.perf_counter()
        doc_res = document_agent(
            scheme_id=target_scheme,
            schemes=schemes,
            lang=session["lang"],
            provider=provider,
        )
        elapsed_doc_ms = int((time.perf_counter() - t_doc) * 1000)

        trace.append({
            "agent": "document",
            "action": f"checklist for {target_scheme} ({len(doc_res['documents'])} items)",
            "ms": elapsed_doc_ms,
        })

        session_id_str = session.get("session_id", "")
        form_url = f"/form/{target_scheme}" + (f"?session_id={session_id_str}&auto_print=true" if session_id_str else "?auto_print=true")
        reminders_url = f"/reminders.ics?scheme_id={target_scheme}" + (f"&session_id={session_id_str}" if session_id_str else "")

        if session["lang"] == "hi":
            actions_text = (
                f"\n\n\U0001f4e5 [\u092f\u0939\u093e\u0901 \u0915\u094d\u0932\u093f\u0915 \u0915\u0930\u0915\u0947 \u0906\u0935\u0947\u0926\u0928 \u092a\u094dरारूप \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u0915\u0930\u0947ं (Download PDF)]({form_url})\n"
                f"\U0001f4c5 [\u092f\u0939\u093e\u0901 \u0915\u094d\u0932\u093f\u0915 \u0915\u0930\u0915\u0947 \u0915\u0948\u0932\u0947\u0902\u0921\u0930 \u0930\u093f\u092e\u093eइ\u0902\u0921\u0930 \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u0915\u0930\u0947ं (Download reminders)]({reminders_url})\n"
            )
        else:
            actions_text = (
                f"\n\n\U0001f4e5 [Click here to Download PDF Draft]({form_url})\n"
                f"\U0001f4c5 [Click here to Download reminders (.ics)]({reminders_url})\n"
            )

        reply = f"{doc_res['reply'].strip()}\n{actions_text}" 

    elif current_state in {"COLLECT_PROFILE", "MATCH"}:
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
        # Default fallback for advanced states (FORM, REMINDERS, etc.)
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
