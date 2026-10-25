"""Agents for Sahayak: Profile Agent, Eligibility Agent, and tools.

Each agent follows docs/ARCHITECTURE.md, docs/DATA_SCHEMA.md, and PRD guidelines.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from eligibility import evaluate_all, evaluate_scheme, load_schemes
from llm import generate_json, generate_text

logger = logging.getLogger("sahayak.agents")

# Valid profile schema keys per docs/DATA_SCHEMA.md
VALID_PROFILE_FIELDS = {
    "name",
    "age",
    "gender",
    "state",
    "district",
    "occupation",
    "land_acres",
    "annual_income",
    "category",
    "bpl_household",
    "education_level",
    "has_lpg_connection",
}

# Ordered priority for asking follow-up questions
FIELD_PRIORITY = [
    "occupation",
    "annual_income",
    "land_acres",
    "gender",
    "age",
    "bpl_household",
    "has_lpg_connection",
    "education_level",
    "state",
    "district",
    "category",
    "name",
]

HINDI_FOLLOWUPS = {
    "occupation": "आप क्या काम करते हैं? (जैसे: किसान, छात्र, मजदूर या नौकरीपेशा)",
    "annual_income": "आपके परिवार की कुल सालाना (वार्षिक) आय लगभग कितनी है?",
    "land_acres": "आपके पास कितने एकड़ खेती योग्य ज़मीन है?",
    "gender": "आप महिला हैं या पुरुष?",
    "bpl_household": "क्या आपका परिवार गरीब / बीपीएल (BPL) श्रेणी या राशन कार्ड धारक है?",
    "has_lpg_connection": "क्या आपके घर में किसी के पास पहले से एलपीजी गैस सिलेंडर कनेक्शन है?",
    "age": "आपकी उम्र कितने वर्ष है?",
    "state": "आप किस राज्य में रहते हैं?",
    "district": "आप किस जिले के रहने वाले हैं?",
    "education_level": "आपकी वर्तमान शिक्षा या कक्षा क्या है?",
    "category": "आपकी सामाजिक श्रेणी क्या है? (जैसे: सामान्य, ओबीसी, एससी, एसटी)",
    "name": "आपका शुभ नाम क्या है?",
}

ENGLISH_FOLLOWUPS = {
    "occupation": "What is your occupation? (e.g., farmer, student, labourer, salaried, self-employed)",
    "annual_income": "What is your approximate family annual income in rupees?",
    "land_acres": "How many acres of cultivable agricultural land do you own?",
    "gender": "What is your gender? (female, male, other)",
    "bpl_household": "Does your household belong to the BPL category or have a ration card?",
    "has_lpg_connection": "Does your household already have an existing LPG gas cylinder connection?",
    "age": "What is your age in years?",
    "state": "Which state do you live in?",
    "district": "Which district do you reside in?",
    "education_level": "What is your current education level? (e.g. 10th, 12th, college)",
    "category": "What is your social category? (general, OBC, SC, ST)",
    "name": "May I have your name?",
}

HINDI_DISCLAIMER = "कृपया आधिकारिक पोर्टल पर जाकर नियमों का सत्यापन अवश्य करें।"
ENGLISH_DISCLAIMER = "Please verify all rules and details on the official portal."


PROFILE_SYSTEM_PROMPT = """You are the Profile Agent for Sahayak, a citizen assistance platform in India.
Your task is to extract user profile fields from user speech/text in Hindi, English, or mixed (Hinglish).

Allowed profile fields and types (strictly according to docs/DATA_SCHEMA.md):
- name: string
- age: integer
- gender: "male" | "female" | "other"
- state: string (e.g. "Uttar Pradesh", "Bihar")
- district: string (e.g. "Unnao", "Patna")
- occupation: "farmer" | "student" | "labourer" | "salaried" | "self_employed" | "unemployed" | "other"
- land_acres: float (number of acres of cultivable land owned)
- annual_income: integer (annual household income in INR)
- category: "general" | "obc" | "sc" | "st" | "other"
- bpl_household: boolean (true if below poverty line / ration card holder / SECC poor)
- education_level: string (e.g. "class_10", "class_12", "graduate")
- has_lpg_connection: boolean (true if the household already has an LPG cylinder connection)

HARD RULES:
1. ONLY output fields mentioned by the user. Do NOT guess, invent, or assume any values not stated.
2. If a field is not mentioned, omit it or set it to null.
3. Detect the user's primary language as "hi" (Hindi / Hinglish / mixed) or "en" (English).
4. Output a JSON object with two top-level keys:
   - "extracted_fields": { ... only stated fields with non-null values ... }
   - "detected_language": "hi" or "en"
"""

ELIGIBILITY_SYSTEM_PROMPT = """You are the Eligibility Agent for Sahayak, an Indian citizen welfare assistant.

STRICT GUARDRAILS:
1. You may ONLY state facts present in schemes.json provided in the prompt.
2. NEVER invent, hallucinate, or extrapolate amounts, dates, rules, eligibility conditions, or web links. If unknown or not specified, say so and point to the official link.
3. Every scheme mentioned MUST include its verified official link.
4. Every response MUST include one line stating to verify on the official portal:
   - In Hindi: "कृपया आधिकारिक पोर्टल पर जाकर नियमों का सत्यापन अवश्य करें।"
   - In English: "Please verify all rules and details on the official portal."
5. If the citizen is not eligible for any scheme, explain politely and honestly without inventing any schemes.
"""


def _sanitize_profile_fields(raw_fields: dict[str, Any]) -> dict[str, Any]:
    """Clean, filter, and cast extracted fields to standard types."""
    clean: dict[str, Any] = {}
    for key, val in raw_fields.items():
        if key not in VALID_PROFILE_FIELDS or val is None or val == "":
            continue

        if key in {"age", "annual_income"}:
            try:
                clean_num = str(val).replace(",", "").strip()
                clean[key] = int(float(clean_num))
            except (ValueError, TypeError):
                continue
        elif key == "land_acres":
            try:
                clean_num = str(val).replace(",", "").strip()
                clean[key] = float(clean_num)
            except (ValueError, TypeError):
                continue
        elif key in {"bpl_household", "has_lpg_connection"}:
            if isinstance(val, bool):
                clean[key] = val
            elif isinstance(val, str):
                v_lower = val.strip().lower()
                if v_lower in {"true", "1", "yes", "हाँ", "ha", "haan"}:
                    clean[key] = True
                elif v_lower in {"false", "0", "no", "नहीं", "nahi", "nahin"}:
                    clean[key] = False
        elif key in {"gender", "occupation", "category"}:
            clean[key] = str(val).strip().lower()
        else:
            clean[key] = str(val).strip()

    return clean


# ---------------------------------------------------------------------------
# Profile Agent
# ---------------------------------------------------------------------------


def profile_agent(
    message: str,
    existing_profile: dict[str, Any] | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Profile Agent: extracts profile fields from free text/speech and detects language.

    Args:
        message: User's utterance in Hindi, English, or mixed.
        existing_profile: Current profile dictionary to merge with.
        provider: Optional LLM provider override ("gemini" or "groq").

    Returns:
        dict containing:
            "profile": merged updated profile dictionary with valid fields
            "extracted": newly extracted fields from current turn
            "lang": "hi" or "en"
    """
    base_profile = dict(existing_profile) if existing_profile else {}

    user_prompt = f"""User message: "{message}"

Current known profile: {json.dumps(base_profile, ensure_ascii=False)}

Extract any newly provided or updated profile fields and detect the language."""

    try:
        response_data = generate_json(
            prompt=user_prompt,
            system_prompt=PROFILE_SYSTEM_PROMPT,
            provider=provider,
            temperature=0.1,
        )
    except Exception as exc:
        logger.error("Profile agent extraction error: %s", exc)
        is_hindi = any("\u0900" <= c <= "\u097f" for c in message)
        return {
            "profile": base_profile,
            "extracted": {},
            "lang": "hi" if is_hindi else "en",
        }

    raw_extracted = response_data.get("extracted_fields", {})
    if not isinstance(raw_extracted, dict):
        raw_extracted = {k: v for k, v in response_data.items() if k in VALID_PROFILE_FIELDS}

    detected_lang = response_data.get("detected_language", "").lower()
    if detected_lang not in {"hi", "en"}:
        is_hindi = any("\u0900" <= c <= "\u097f" for c in message)
        detected_lang = "hi" if is_hindi else "en"

    sanitized_extracted = _sanitize_profile_fields(raw_extracted)

    # Merge into existing profile
    updated_profile = dict(base_profile)
    updated_profile.update(sanitized_extracted)

    return {
        "profile": updated_profile,
        "extracted": sanitized_extracted,
        "lang": detected_lang,
    }


extract_profile = profile_agent


# ---------------------------------------------------------------------------
# Missing Fields Ordering
# ---------------------------------------------------------------------------


def get_missing_fields(
    profile: dict[str, Any],
    schemes: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Given profile and schemes, returns missing required fields ordered by importance.

    Excludes missing fields from schemes that are already disqualified (not_eligible).
    Orders results strictly by global importance hierarchy (FIELD_PRIORITY).
    """
    if schemes is None:
        schemes = load_schemes()

    evaluations = [evaluate_scheme(profile, scheme) for scheme in schemes]
    has_eligible = any(e.get("status") == "eligible" for e in evaluations)
    # If the user has already qualified as eligible for one or more schemes, do not ask more follow-ups
    if has_eligible:
        return []

    missing_set: set[str] = set()
    for evaluation in evaluations:
        # Only collect missing fields for schemes that are still viable (status == maybe)
        if evaluation.get("status") == "maybe":
            for f in evaluation.get("missing_fields", []):
                if f not in profile or profile.get(f) is None or profile.get(f) == "":
                    missing_set.add(f)

    # Order according to FIELD_PRIORITY
    ordered: list[str] = [f for f in FIELD_PRIORITY if f in missing_set]
    for f in sorted(missing_set):
        if f not in ordered:
            ordered.append(f)

    return ordered


# ---------------------------------------------------------------------------
# Eligibility Agent
# ---------------------------------------------------------------------------


def eligibility_agent(
    profile: dict[str, Any],
    schemes: list[dict[str, Any]] | None = None,
    lang: str = "hi",
    provider: str | None = None,
) -> dict[str, Any]:
    """Eligibility Agent:
    - If fields are missing: asks exactly ONE short follow-up question in the user's language.
    - Otherwise: calls evaluate_all and explains results in simple language with official links and disclaimer.

    Returns:
        dict:
            "reply": str
            "needs_follow_up": bool
            "missing_field": str | None
            "missing_fields": list[str]
            "matches": list[dict[str, Any]]
    """
    if schemes is None:
        schemes = load_schemes()

    missing_fields = get_missing_fields(profile, schemes)
    evaluation_results = evaluate_all(profile, schemes, lang=lang)
    scheme_by_id = {s["id"]: s for s in schemes}

    enriched_matches: list[dict[str, Any]] = []
    for r in evaluation_results:
        s_data = scheme_by_id.get(r["scheme_id"], {})
        enriched_matches.append({
            **r,
            "name": s_data.get("name_hi" if lang == "hi" else "name_en", r["scheme_id"]),
            "benefit": s_data.get("benefit_hi" if lang == "hi" else "benefit_en", ""),
            "official_link": s_data.get("official_link", ""),
        })

    # 1. If fields are missing: ask exactly ONE short follow-up question
    if missing_fields:
        next_field = missing_fields[0]
        question_map = HINDI_FOLLOWUPS if lang == "hi" else ENGLISH_FOLLOWUPS
        follow_up_q = question_map.get(
            next_field,
            f"कृपया अपना {next_field} बताएं।" if lang == "hi" else f"Please provide your {next_field}."
        )
        return {
            "reply": follow_up_q,
            "needs_follow_up": True,
            "missing_field": next_field,
            "missing_fields": missing_fields,
            "matches": enriched_matches,
        }

    # 2. All required fields are present: evaluate schemes deterministically
    eligible_schemes: list[dict[str, Any]] = []
    for r in enriched_matches:
        if r["status"] == "eligible":
            eligible_schemes.append({
                "id": r["scheme_id"],
                "name": r.get("name", r["scheme_id"]),
                "benefit": r.get("benefit", ""),
                "official_link": r.get("official_link", ""),
                "reasons_met": r.get("reasons_met", []),
            })

    disclaimer = HINDI_DISCLAIMER if lang == "hi" else ENGLISH_DISCLAIMER

    # Prepare guarded prompt for LLM explanation
    if eligible_schemes:
        prompt = f"""Language: {lang}
Verified eligible schemes:
{json.dumps(eligible_schemes, ensure_ascii=False, indent=2)}

Explain these matches to the citizen in simple, warm {'Hindi' if lang == 'hi' else 'English'}.
CRITICAL RULES:
1. ONLY state facts from the verified data above. Never invent amounts, dates, or portals.
2. For every scheme mentioned, include its name, benefit, and official link.
3. You MUST conclude your response with this exact line:
   "{disclaimer}"
Keep it concise and clear."""
    else:
        prompt = f"""Language: {lang}
The user is not currently eligible for any verified scheme.
Politely and warmly explain this in {'Hindi' if lang == 'hi' else 'English'}.
CRITICAL RULES:
1. Do NOT invent or suggest any other schemes.
2. You MUST conclude your response with this exact line:
   "{disclaimer}"
Keep it short and encouraging."""

    try:
        reply = generate_text(
            prompt=prompt,
            system_prompt=ELIGIBILITY_SYSTEM_PROMPT,
            provider=provider,
            temperature=0.2,
        )
        # Guardrail checks: ensure disclaimer and links are always present
        if disclaimer not in reply:
            reply = f"{reply.strip()}\n\n{disclaimer}"
        for s in eligible_schemes:
            link = s["official_link"]
            if link and link not in reply:
                reply = f"{reply.strip()}\n{s['name']}: {link}"
    except Exception as exc:
        logger.warning("LLM explanation generation failed: %s. Using structured template.", exc)
        if eligible_schemes:
            if lang == "hi":
                lines = ["आपकी जानकारी के आधार पर आप निम्नलिखित सरकारी योजनाओं के लिए पात्र हैं:\n"]
                for s in eligible_schemes:
                    lines.append(f"• **{s['name']}**\n  लाभ: {s['benefit']}\n  आधिकारिक पोर्टल: {s['official_link']}")
                lines.append(f"\n{disclaimer}")
                reply = "\n".join(lines)
            else:
                lines = ["Based on your details, you are eligible for the following government schemes:\n"]
                for s in eligible_schemes:
                    lines.append(f"• **{s['name']}**\n  Benefit: {s['benefit']}\n  Official portal: {s['official_link']}")
                lines.append(f"\n{disclaimer}")
                reply = "\n".join(lines)
        else:
            if lang == "hi":
                reply = f"वर्तमान जानकारी के आधार पर अभी आप किसी योजना के लिए सीधे पात्र नहीं हैं।\n\n{disclaimer}"
            else:
                reply = f"Based on your details, no matching scheme was found.\n\n{disclaimer}"

    return {
        "reply": reply,
        "needs_follow_up": False,
        "missing_field": None,
        "missing_fields": [],
        "matches": evaluation_results,
    }
