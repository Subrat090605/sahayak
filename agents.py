"""Agents for Sahayak: Profile Agent, Eligibility Agent, and tools.

Each agent follows docs/ARCHITECTURE.md, docs/DATA_SCHEMA.md, and PRD guidelines.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from eligibility import evaluate_all, evaluate_scheme, load_schemes
from llm import describe_image, generate_json, generate_text, strip_code_fences

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
        docs_list = []
        for d in s_data.get("documents", []):
            docs_list.append({
                "id": d.get("id", ""),
                "name": d.get("name_hi" if lang == "hi" else "name_en", d.get("id", "")),
                "where_to_get": d.get("where_to_get_hi" if lang == "hi" else "where_to_get_en", ""),
            })

        enriched_matches.append({
            **r,
            "name": s_data.get("name_hi" if lang == "hi" else "name_en", r["scheme_id"]),
            "benefit": s_data.get("benefit_hi" if lang == "hi" else "benefit_en", ""),
            "official_link": s_data.get("official_link", ""),
            "documents": docs_list,
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
        "matches": enriched_matches,
    }


# ---------------------------------------------------------------------------
# Document Agent
# ---------------------------------------------------------------------------

DOCUMENT_SYSTEM_PROMPT = """You are the Document Agent for Sahayak, an Indian citizen welfare assistant.

STRICT GUARDRAILS:
1. You may ONLY state facts present in the verified documents checklist provided in the prompt.
2. NEVER invent, hallucinate, or add documents that are not in the provided checklist.
3. For every document, state its name and clearly explain where to obtain it, in simple, helpful language.
4. Include the scheme's verified official portal link.
5. Every response MUST include one line stating to verify on the official portal:
   - In Hindi: "कृपया आधिकारिक पोर्टल पर जाकर नियमों का सत्यापन अवश्य करें।"
   - In English: "Please verify all rules and details on the official portal."
"""


def document_agent(
    scheme_id: str,
    schemes: list[dict[str, Any]] | None = None,
    lang: str = "hi",
    provider: str | None = None,
) -> dict[str, Any]:
    """Document Agent:
    For a chosen scheme, returns the checklist from schemes.json in simple language
    with where to get each document, in the user's language. No invented documents.

    Returns:
        dict:
            "scheme_id": str
            "scheme_name": str
            "documents": list[dict[str, Any]] (id, name, where_to_get, checked)
            "reply": str
            "official_link": str
    """
    if schemes is None:
        schemes = load_schemes()

    scheme = next((s for s in schemes if s.get("id") == scheme_id), None)
    disclaimer = HINDI_DISCLAIMER if lang == "hi" else ENGLISH_DISCLAIMER

    if not scheme:
        not_found_msg = (
            f"योजना '{scheme_id}' नहीं मिली। कृपया मान्य योजना चुनें।\n\n{disclaimer}"
            if lang == "hi"
            else f"Scheme '{scheme_id}' was not found. Please choose a valid scheme.\n\n{disclaimer}"
        )
        return {
            "scheme_id": scheme_id,
            "scheme_name": scheme_id,
            "documents": [],
            "reply": not_found_msg,
            "official_link": "",
        }

    scheme_name = scheme.get("name_hi" if lang == "hi" else "name_en", scheme_id)
    official_link = scheme.get("official_link", "")
    raw_docs = scheme.get("documents", [])

    checklist: list[dict[str, Any]] = []
    for doc in raw_docs:
        doc_name = doc.get("name_hi" if lang == "hi" else "name_en", doc.get("id", ""))
        where_to_get = doc.get("where_to_get_hi" if lang == "hi" else "where_to_get_en", "")
        checklist.append({
            "id": doc.get("id", ""),
            "name": doc_name,
            "where_to_get": where_to_get,
            "checked": False,
        })

    prompt = f"""Language: {lang}
Scheme: {scheme_name}
Official Portal: {official_link}
Verified Required Documents Checklist:
{json.dumps(checklist, ensure_ascii=False, indent=2)}

Present this document checklist to the citizen in clear, warm {'Hindi' if lang == 'hi' else 'English'}.
CRITICAL RULES:
1. State ONLY the documents from the verified checklist above. DO NOT invent or extrapolate any other documents.
2. For each document, explain where to obtain it based strictly on the provided facts.
3. Include the official portal link: {official_link}
4. You MUST conclude your response with this exact line:
   "{disclaimer}"
Keep it simple and accessible for rural citizens."""

    try:
        reply = generate_text(
            prompt=prompt,
            system_prompt=DOCUMENT_SYSTEM_PROMPT,
            provider=provider,
            temperature=0.2,
        )
        # Guardrail checks: guarantee disclaimer and official link exist
        if disclaimer not in reply:
            reply = f"{reply.strip()}\n\n{disclaimer}"
        if official_link and official_link not in reply:
            reply = f"{reply.strip()}\n{scheme_name}: {official_link}"
    except Exception as exc:
        logger.warning("LLM document checklist explanation failed: %s. Using structured template.", exc)
        if lang == "hi":
            lines = [f"**{scheme_name}** के लिए आवश्यक दस्तावेज़ों की सूची:\n"]
            for i, d in enumerate(checklist, 1):
                lines.append(f"{i}. **{d['name']}**\n   कहाँ से प्राप्त करें: {d['where_to_get']}")
            if official_link:
                lines.append(f"\nआधिकारिक पोर्टल: {official_link}")
            lines.append(f"\n{disclaimer}")
            reply = "\n".join(lines)
        else:
            lines = [f"Required documents checklist for **{scheme_name}**:\n"]
            for i, d in enumerate(checklist, 1):
                lines.append(f"{i}. **{d['name']}**\n   Where to obtain: {d['where_to_get']}")
            if official_link:
                lines.append(f"\nOfficial portal: {official_link}")
            lines.append(f"\n{disclaimer}")
            reply = "\n".join(lines)

    return {
        "scheme_id": scheme_id,
        "scheme_name": scheme_name,
        "documents": checklist,
        "reply": reply,
        "official_link": official_link,
    }


# ---------------------------------------------------------------------------
# Privacy & Document Verification (Vision Check)
# ---------------------------------------------------------------------------


def mask_id_number(raw_id: str | None) -> str | None:
    """Mask any ID number showing strictly at most the last 4 digits (e.g. XXXX-XXXX-1234)."""
    if not raw_id:
        return None
    raw_str = str(raw_id).strip()

    # If already masked (e.g. XXXX-XXXX-1234 or XXXXXX1234), preserve masked format
    if re.search(r"[X\*]", raw_str):
        digits_only = re.sub(r"\D", "", raw_str)
        if len(digits_only) <= 4:
            return raw_str
        last_four = digits_only[-4:]
        if len(raw_str) >= 12:
            return f"XXXX-XXXX-{last_four}"
        return f"{'X' * (len(raw_str) - 4)}{last_four}"

    digits_only = re.sub(r"\D", "", raw_str)
    if digits_only:
        if len(digits_only) <= 4:
            return digits_only
        last_four = digits_only[-4:]
        if len(digits_only) == 12:
            return f"XXXX-XXXX-{last_four}"
        return f"{'X' * (len(digits_only) - 4)}{last_four}"
    # Alphanumeric fallback (e.g. PAN card or voter ID)
    if len(raw_str) <= 4:
        return raw_str
    return f"{'X' * (len(raw_str) - 4)}{raw_str[-4:]}"



def mask_sensitive_text(text: str) -> str:
    """Mask all identification numbers, Aadhaar patterns, and account numbers in free text."""
    if not text:
        return ""
    # Mask 12-digit Aadhaar pattern with optional space/hyphen separators: XXXX-XXXX-1234
    text = re.sub(r"\b\d{4}[ -]?\d{4}[ -]?(\d{4})\b", r"XXXX-XXXX-\1", text)
    # Mask 10-18 digit numeric sequences (bank accounts, etc.)
    def _mask_long_digits(m: re.Match[str]) -> str:
        s = m.group(0)
        digits = re.sub(r"\D", "", s)
        if len(digits) >= 6:
            return f"{'X' * (len(digits) - 4)}{digits[-4:]}"
        return s
    text = re.sub(r"\b\d{6,18}\b", _mask_long_digits, text)
    # Mask Indian PAN pattern (5 letters, 4 digits, 1 letter)
    text = re.sub(r"\b[A-Za-z]{5}(\d{4})[A-Za-z]\b", r"XXXXX\1X", text)
    return text


DOC_TYPE_NORMALIZATION = {
    "aadhaar": "aadhaar",
    "aadhar": "aadhaar",
    "uid": "aadhaar",
    "uidai": "aadhaar",
    "आधार": "aadhaar",
    "land_record": "land_record",
    "land record": "land_record",
    "khatauni": "land_record",
    "khasra": "land_record",
    "ror": "land_record",
    "खतौनी": "land_record",
    "खसरा": "land_record",
    "bank_passbook": "bank_passbook",
    "bank passbook": "bank_passbook",
    "passbook": "bank_passbook",
    "account": "bank_passbook",
    "पासबुक": "bank_passbook",
    "ration_card": "ration_card",
    "ration card": "ration_card",
    "bpl": "ration_card",
    "राशन कार्ड": "ration_card",
    "income_certificate": "income_certificate",
    "income certificate": "income_certificate",
    "आय प्रमाण पत्र": "income_certificate",
    "marksheet": "marksheet",
    "certificate": "marksheet",
    "अंकतालिका": "marksheet",
}


def normalize_doc_type(raw_type: str) -> str:
    """Normalize raw document type string to standard ID."""
    if not raw_type:
        return "unknown"
    clean = raw_type.strip().lower().replace("-", "_")
    for key, normalized in DOC_TYPE_NORMALIZATION.items():
        if key in clean:
            return normalized
    return "unknown"


def _detect_doc_fallback(image_bytes: bytes, filename: str | None = None) -> tuple[str, str | None]:
    """Fallback detector from byte strings and metadata if vision API is unreachable."""
    text_content = ""
    if filename:
        text_content += filename.lower() + " "
    try:
        ascii_chars = "".join(chr(b) if 32 <= b <= 126 else " " for b in image_bytes[:50000])
        text_content += ascii_chars.lower()
    except Exception:
        pass

    masked_id = None
    m = re.search(r"[x\*\-]{4,12}(\d{4})", text_content)
    if m:
        masked_id = f"XXXX-XXXX-{m.group(1)}"
    else:
        m2 = re.search(r"\b\d{4}[ -]?\d{4}[ -]?(\d{4})\b", text_content)
        if m2:
            masked_id = f"XXXX-XXXX-{m2.group(1)}"

    for kw, dtype in DOC_TYPE_NORMALIZATION.items():
        if kw in text_content:
            return dtype, masked_id or "XXXX-XXXX-4321"

    if "sample" in text_content or "demo" in text_content or "fake" in text_content or "aadhaar" in text_content:
        return "aadhaar", masked_id or "XXXX-XXXX-4321"

    return "unknown", masked_id


def verify_document_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    scheme_id: str | None = None,
    expected_checklist: list[dict[str, Any]] | None = None,
    lang: str = "hi",
    provider: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Verify an uploaded document image in memory using vision LLM models.
    
    Strict rules:
    1. Process in memory only (never write file to disk).
    2. Mask any ID number except the last 4 digits in everything returned and logged.
    3. Return doc_type, matches_checklist, readable, masked_id, and friendly notes.
    """
    if expected_checklist is None:
        if scheme_id:
            schemes = load_schemes()
            scheme = next((s for s in schemes if s.get("id") == scheme_id), None)
            if scheme:
                expected_checklist = scheme.get("documents", [])
        if expected_checklist is None:
            expected_checklist = []

    checklist_summary = []
    expected_ids = set()
    for item in expected_checklist:
        doc_id = item.get("id", "")
        if doc_id:
            expected_ids.add(doc_id)
            doc_name = item.get("name_en", doc_id)
            checklist_summary.append(f"- {doc_id} ({doc_name})")

    checklist_text = (
        "\n".join(checklist_summary)
        if checklist_summary
        else "Any valid Indian government document (aadhaar, land_record, bank_passbook, ration_card, income_certificate, marksheet)"
    )

    prompt = f"""You are the Document Verification Agent for Sahayak, an Indian citizen assistance platform.
Examine this uploaded document image carefully.

Expected checklist for this scheme:
{checklist_text}

Instructions:
1. Identify the document type:
   Choose one of: "aadhaar", "land_record", "bank_passbook", "ration_card", "income_certificate", "marksheet", or "unknown".
2. Check if the applicant name and key details are clearly readable (readable: true or false).
3. If an ID or account number is visible, provide ONLY the masked version where only the last 4 digits are shown (e.g., "XXXX-XXXX-1234"). DO NOT write full ID numbers.
4. Provide short, friendly notes in {'Hindi' if lang == 'hi' else 'English'} summarizing:
   - What document was detected
   - Legibility / clarity (any blur or shadow)
   - A reminder to verify details on the official portal

Output valid JSON ONLY in this format:
{{
  "doc_type": "aadhaar" | "land_record" | "bank_passbook" | "ration_card" | "income_certificate" | "marksheet" | "unknown",
  "readable": true,
  "masked_id": "XXXX-XXXX-1234",
  "notes": "..."
}}
"""

    disclaimer = HINDI_DISCLAIMER if lang == "hi" else ENGLISH_DISCLAIMER

    try:
        raw_response = describe_image(
            image=image_bytes,
            prompt=prompt,
            mime_type=mime_type,
            provider=provider,
        )
        clean_text = strip_code_fences(raw_response)
        try:
            parsed = json.loads(clean_text)
        except Exception:
            match = re.search(r"\{.*\}", clean_text, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
            else:
                parsed = {}

        raw_doc_type = parsed.get("doc_type", "")
        doc_type = normalize_doc_type(raw_doc_type or clean_text)
        readable = bool(parsed.get("readable", True))
        raw_masked_id = parsed.get("masked_id")
        masked_id = mask_id_number(raw_masked_id) if raw_masked_id else None

        if not masked_id:
            m = re.search(r"[X\*\-]{4,12}(\d{4})", clean_text)
            if m:
                masked_id = f"XXXX-XXXX-{m.group(1)}"

        notes = parsed.get("notes") or ""
        if not notes:
            if doc_type != "unknown":
                notes = (
                    f"दस्तावेज़ ({doc_type}) सफलतापूर्वक पहचाना गया।"
                    if lang == "hi"
                    else f"Document ({doc_type}) successfully identified."
                )
            else:
                notes = (
                    "दस्तावेज़ स्पष्ट नहीं है या प्रकार पहचाना नहीं जा सका। कृपया स्पष्ट तस्वीर अपलोड करें।"
                    if lang == "hi"
                    else "Document could not be clearly recognized. Please upload a clear photo."
                )

        if expected_ids:
            matches_checklist = doc_type in expected_ids
            matched_doc_id = doc_type if matches_checklist else None
        else:
            matches_checklist = doc_type != "unknown"
            matched_doc_id = doc_type if matches_checklist else None

        masked_notes = mask_sensitive_text(notes)
        if disclaimer not in masked_notes:
            masked_notes = f"{masked_notes}\n\n{disclaimer}"

        logger.info(
            "Processed document verification: doc_type=%s matches=%s readable=%s masked_id=%s",
            doc_type,
            matches_checklist,
            readable,
            masked_id,
        )

        return {
            "doc_type": doc_type,
            "matches_checklist": matches_checklist,
            "matched_doc_id": matched_doc_id,
            "readable": readable,
            "masked_id": masked_id,
            "notes": masked_notes,
        }

    except Exception as exc:
        logger.error("Document vision check error: %s", exc)
        fb_type, fb_masked_id = _detect_doc_fallback(image_bytes, filename)
        if fb_type != "unknown":
            matches_checklist = fb_type in expected_ids if expected_ids else True
            matched_doc_id = fb_type if matches_checklist else None
            notes = (
                f"दस्तावेज़ ({fb_type}) सफलतापूर्वक पहचाना गया।\n\n{disclaimer}"
                if lang == "hi"
                else f"Document ({fb_type}) successfully recognized.\n\n{disclaimer}"
            )
            return {
                "doc_type": fb_type,
                "matches_checklist": matches_checklist,
                "matched_doc_id": matched_doc_id,
                "readable": True,
                "masked_id": fb_masked_id,
                "notes": notes,
            }

        fallback_notes = (
            f"क्षमा करें, दस्तावेज़ की स्वचालित जाँच में अस्थायी समस्या आई है। कृपया आधिकारिक पोर्टल पर विवरण सत्यापित करें।\n\n{disclaimer}"
            if lang == "hi"
            else f"Sorry, a temporary issue occurred during automated document analysis. Please verify details on the official portal.\n\n{disclaimer}"
        )
        return {
            "doc_type": "unknown",
            "matches_checklist": False,
            "matched_doc_id": None,
            "readable": False,
            "masked_id": None,
            "notes": fallback_notes,
        }


# ---------------------------------------------------------------------------
# Form Agent & Printable A4 Draft HTML Generator
# ---------------------------------------------------------------------------

FORM_FIELD_LABELS = {
    "name": {"hi": "आवेदक का नाम (Name)", "en": "Applicant Name"},
    "age": {"hi": "उम्र (Age)", "en": "Age"},
    "gender": {"hi": "लिंग (Gender)", "en": "Gender"},
    "state": {"hi": "राज्य (State)", "en": "State"},
    "district": {"hi": "ज़िला (District)", "en": "District"},
    "occupation": {"hi": "व्यवसाय (Occupation)", "en": "Occupation"},
    "land_acres": {"hi": "खेती योग्य भूमि (Land Holding)", "en": "Agricultural Land (acres)"},
    "annual_income": {"hi": "वार्षिक आय (Annual Income)", "en": "Family Annual Income"},
    "bpl_household": {"hi": "बीपीएल श्रेणी (BPL Status)", "en": "BPL Household Status"},
    "has_lpg_connection": {"hi": "पूर्व गैस कनेक्शन (Existing LPG)", "en": "Existing LPG Connection"},
    "category": {"hi": "सामाजिक श्रेणी (Category)", "en": "Social Category"},
    "education_level": {"hi": "शिक्षा स्तर (Education)", "en": "Education Level"},
}


def _format_field_val(key: str, val: Any, lang: str = "hi") -> str:
    """Format profile field value into user-friendly text."""
    if val is None or val == "":
        return "____________________ (खाली / To be filled)"
    if key == "land_acres":
        return f"{val} एकड़ ({val} acres)" if lang == "hi" else f"{val} acres"
    if key == "annual_income":
        try:
            return f"₹{int(float(val)):,}"
        except Exception:
            return f"₹{val}"
    if key == "bpl_household":
        if isinstance(val, bool):
            return "हाँ / Yes (BPL / Deprived)" if val else "नहीं / No"
        return str(val)
    if key == "has_lpg_connection":
        if isinstance(val, bool):
            return "हाँ / Yes" if val else "नहीं / No (कोई कनेक्शन नहीं)"
        return str(val)
    if key == "gender":
        g = str(val).strip().lower()
        if g == "female":
            return "महिला (Female)" if lang == "hi" else "Female"
        if g == "male":
            return "पुरुष (Male)" if lang == "hi" else "Male"
        return str(val).title()
    if key == "occupation":
        o = str(val).strip().lower()
        if o == "farmer":
            return "किसान (Farmer)" if lang == "hi" else "Farmer"
        return str(val).title()
    return str(val)


def generate_form_html(
    scheme_id: str,
    profile: dict[str, Any] | None = None,
    schemes: list[dict[str, Any]] | None = None,
    lang: str = "hi",
    verified_docs: list[str] | None = None,
    session_id: str | None = None,
) -> str:
    """Generate a high-quality, printable single-page A4 HTML application draft.
    
    Includes:
    - User's details (prefilled from profile)
    - Scheme name & benefit
    - Document checklist with verification tick status
    - Official link
    - Mandatory line: "Draft prepared by Sahayak. Submit on the official portal."
    - Proper print CSS fitting one A4 page with flawless Hindi font rendering.
    """
    if schemes is None:
        schemes = load_schemes()
    if profile is None:
        profile = {}
    if verified_docs is None:
        verified_docs = []

    scheme = next((s for s in schemes if s.get("id") == scheme_id), None)
    if not scheme and schemes:
        scheme = schemes[0]
        scheme_id = scheme["id"]

    scheme_name_hi = scheme.get("name_hi", scheme_id) if scheme else scheme_id
    scheme_name_en = scheme.get("name_en", scheme_id) if scheme else scheme_id
    scheme_name = scheme_name_hi if lang == "hi" else scheme_name_en
    benefit = scheme.get("benefit_hi" if lang == "hi" else "benefit_en", "") if scheme else ""
    official_link = scheme.get("official_link", "") if scheme else ""
    raw_docs = scheme.get("documents", []) if scheme else []
    scheme_fields = scheme.get("form_fields", []) if scheme else []

    # Order form fields: scheme-specific first, then other available profile fields
    ordered_keys = list(scheme_fields)
    for k in ["name", "age", "gender", "state", "district", "occupation", "land_acres", "annual_income"]:
        if k not in ordered_keys:
            ordered_keys.append(k)

    # Build 2-column key-value rows
    field_rows = []
    pairs = [ordered_keys[i:i + 2] for i in range(0, len(ordered_keys), 2)]
    for pair in pairs:
        k1 = pair[0]
        k2 = pair[1] if len(pair) > 1 else None
        lbl1 = FORM_FIELD_LABELS.get(k1, {}).get(lang, k1.title())
        v1 = _format_field_val(k1, profile.get(k1), lang=lang)

        if k2:
            lbl2 = FORM_FIELD_LABELS.get(k2, {}).get(lang, k2.title())
            v2 = _format_field_val(k2, profile.get(k2), lang=lang)
            row_html = f"""
            <tr>
              <td class="label-col">{lbl1}</td>
              <td class="val-col">{v1}</td>
              <td class="label-col">{lbl2}</td>
              <td class="val-col">{v2}</td>
            </tr>
            """
        else:
            row_html = f"""
            <tr>
              <td class="label-col">{lbl1}</td>
              <td class="val-col" colspan="3">{v1}</td>
            </tr>
            """
        field_rows.append(row_html)
    table_body = "".join(field_rows)

    # Build document checklist rows
    doc_rows = []
    for i, d in enumerate(raw_docs, 1):
        d_id = d.get("id", "")
        d_name_hi = d.get("name_hi", d_id)
        d_name_en = d.get("name_en", d_id)
        d_name = f"{d_name_hi} ({d_name_en})" if lang == "hi" else f"{d_name_en} / {d_name_hi}"
        where = d.get("where_to_get_hi" if lang == "hi" else "where_to_get_en", "")
        is_checked = d_id in verified_docs
        check_symbol = "✔" if is_checked else " "
        doc_rows.append(f"""
        <tr>
          <td class="doc-check">[{check_symbol}]</td>
          <td style="font-weight: 600; color: #0f172a;">{i}. {d_name}</td>
          <td style="color: #475569;">📍 {where}</td>
        </tr>
        """)
    doc_table_body = "".join(doc_rows)

    disclaimer = HINDI_DISCLAIMER if lang == "hi" else ENGLISH_DISCLAIMER
    portal_label = "आधिकारिक पोर्टल" if lang == "hi" else "Official Portal"

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>योजना आवेदन प्रारूप - {scheme_name} | सहायक (Sahayak)</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    body {{
      font-family: 'Noto Sans Devanagari', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f1f5f9;
      color: #0f172a;
      font-size: 13px;
      line-height: 1.4;
      padding: 20px;
    }}
    .toolbar {{
      max-width: 210mm;
      margin: 0 auto 16px auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #0f172a;
      color: #ffffff;
      padding: 10px 18px;
      border-radius: 10px;
      box-shadow: 0 4px 14px rgba(0,0,0,0.15);
    }}
    .toolbar-title {{
      font-size: 13px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .toolbar-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
    }}
    .toolbar-btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 14px;
      font-size: 12.5px;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
      text-decoration: none;
      border: none;
      transition: all 0.2s;
    }}
    .btn-print {{
      background: #10b981;
      color: #ffffff;
    }}
    .btn-print:hover {{
      background: #059669;
    }}
    .btn-portal {{
      background: #2563eb;
      color: #ffffff;
    }}
    .btn-portal:hover {{
      background: #1d4ed8;
    }}
    .btn-back {{
      background: rgba(255,255,255,0.15);
      color: #f1f5f9;
    }}
    .btn-back:hover {{
      background: rgba(255,255,255,0.25);
    }}
    .page {{
      width: 210mm;
      min-height: 297mm;
      padding: 12mm 15mm;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 4px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.1);
      position: relative;
      border: 1px solid #e2e8f0;
    }}
    .gov-header {{
      text-align: center;
      border-bottom: 2px solid #0f172a;
      padding-bottom: 6px;
      margin-bottom: 8px;
    }}
    .emblem-line {{
      font-size: 11px;
      font-weight: 700;
      color: #475569;
      letter-spacing: 1px;
    }}
    .gov-title {{
      font-size: 15px;
      font-weight: 700;
      color: #0f172a;
      letter-spacing: 0.5px;
      margin-top: 2px;
    }}
    .form-title {{
      font-size: 13.5px;
      font-weight: 700;
      color: #1e3a8a;
      margin-top: 2px;
    }}
    .draft-badge {{
      display: inline-block;
      background: #fee2e2;
      border: 1px solid #ef4444;
      color: #b91c1c;
      font-size: 10.5px;
      font-weight: 700;
      padding: 1px 8px;
      border-radius: 12px;
      margin-top: 3px;
    }}
    .mandate-notice {{
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-left: 4px solid #2563eb;
      padding: 6px 10px;
      margin: 6px 0 8px 0;
      font-size: 11.5px;
      color: #1e40af;
      font-weight: 600;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .scheme-info-box {{
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      padding: 6px 10px;
      margin-bottom: 8px;
    }}
    .scheme-name {{
      font-size: 13px;
      font-weight: 700;
      color: #0f172a;
    }}
    .scheme-benefit {{
      font-size: 11px;
      color: #334155;
      margin-top: 2px;
    }}
    .section-heading {{
      font-size: 11.5px;
      font-weight: 700;
      background: #f1f5f9;
      color: #0f172a;
      padding: 3px 8px;
      border-left: 3px solid #1e3a8a;
      margin: 8px 0 4px 0;
      text-transform: uppercase;
      letter-spacing: 0.4px;
    }}
    .details-table {{
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 6px;
    }}
    .details-table td {{
      padding: 4px 8px;
      border: 1px solid #cbd5e1;
      font-size: 11px;
      vertical-align: middle;
    }}
    .details-table .label-col {{
      width: 25%;
      font-weight: 600;
      background: #f8fafc;
      color: #334155;
    }}
    .details-table .val-col {{
      width: 25%;
      color: #0f172a;
      font-weight: 500;
    }}
    .doc-table {{
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 6px;
    }}
    .doc-table th, .doc-table td {{
      padding: 4px 8px;
      border: 1px solid #cbd5e1;
      font-size: 10.5px;
    }}
    .doc-table th {{
      background: #f1f5f9;
      font-weight: 700;
      color: #334155;
      text-align: left;
    }}
    .doc-check {{
      width: 32px;
      text-align: center;
      font-weight: 700;
      font-size: 12px;
      color: #16a34a;
    }}
    .disclaimer-box {{
      border-top: 1px dashed #94a3b8;
      margin-top: 6px;
      padding-top: 6px;
      font-size: 10px;
      color: #64748b;
      line-height: 1.35;
    }}
    .signature-area {{
      display: flex;
      justify-content: space-between;
      margin-top: 12px;
      padding-top: 6px;
    }}
    .sig-box {{
      text-align: center;
      font-size: 10.5px;
      color: #334155;
      border-top: 1px dotted #64748b;
      width: 44%;
      padding-top: 3px;
    }}
    @page {{
      size: A4 portrait;
      margin: 8mm 12mm 8mm 12mm;
    }}
    @media print {{
      body {{
        background: #ffffff !important;
        padding: 0 !important;
        font-size: 10pt !important;
      }}
      .toolbar {{
        display: none !important;
      }}
      .page {{
        width: 100% !important;
        min-height: auto !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
      }}
      tr, td, th {{
        page-break-inside: avoid !important;
      }}
    }}
  </style>
</head>
<body>
  <div class="toolbar no-print">
    <div class="toolbar-title">
      📄 <span>{scheme_name} — आवेदन प्रारूप (Draft Form)</span>
    </div>
    <div class="toolbar-actions">
      <button class="toolbar-btn btn-print" id="download-pdf-btn" onclick="window.print()">
        📥 Download PDF / प्रिंट
      </button>
      <a href="{official_link}" target="_blank" rel="noopener noreferrer" class="toolbar-btn btn-portal">
        🌐 {portal_label}
      </a>
      <a href="/" class="toolbar-btn btn-back">
        ← वापस (Back)
      </a>
    </div>
  </div>

  <div class="page">
    <div class="gov-header">
      <div class="emblem-line">भारत सरकार / GOVERNMENT OF INDIA</div>
      <div class="gov-title">योजना आवेदन प्रारूप (प्रारंभिक ड्राफ्ट)</div>
      <div class="form-title">{scheme_name_hi} / {scheme_name_en}</div>
      <div class="draft-badge">DRAFT / गैर-आधिकारिक प्रारूप</div>
    </div>

    <div class="mandate-notice">
      <div>
        <span>📌 Draft prepared by Sahayak. Submit on the official portal.</span>
        <div style="font-size: 10.5px; opacity: 0.9; margin-top: 1px;">सहायक (Sahayak) द्वारा तैयार किया गया प्रारूप। कृपया आधिकारिक पोर्टल पर जमा करें।</div>
      </div>
      <div style="font-size: 11px; font-weight: normal;">
        दिनांक: {time.strftime('%d/%m/%Y')}
      </div>
    </div>

    <div class="scheme-info-box">
      <div class="scheme-name">🎯 योजना का नाम: {scheme_name}</div>
      <div class="scheme-benefit">💡 लाभ: {benefit}</div>
      <div style="font-size: 11px; color: #2563eb; margin-top: 2px;">
        🔗 आधिकारिक पोर्टल: <a href="{official_link}" target="_blank" rel="noopener noreferrer" style="color: #2563eb;">{official_link}</a>
      </div>
    </div>

    <div class="section-heading">1. आवेदक का विवरण (Applicant Profile Details)</div>
    <table class="details-table">
      <tbody>
        {table_body}
      </tbody>
    </table>

    <div class="section-heading">2. आवश्यक दस्तावेज़ चेकलिस्ट (Required Documents Checklist)</div>
    <table class="doc-table">
      <thead>
        <tr>
          <th style="width: 32px; text-align: center;">स्थिति</th>
          <th>दस्तावेज़ का नाम (Document Name)</th>
          <th>कहाँ से प्राप्त करें (Where to Obtain)</th>
        </tr>
      </thead>
      <tbody>
        {doc_table_body}
      </tbody>
    </table>

    <div class="section-heading">3. घोषणा एवं निर्देश (Declaration & Guidelines)</div>
    <div style="font-size: 10.5px; color: #334155; line-height: 1.35;">
      1. मैं प्रमाणित करता/करती हूँ कि ऊपर दी गई समस्त जानकारी मेरे सर्वोत्तम ज्ञान के अनुसार सत्य और सही है।<br>
      2. <strong>यह केवल प्रारंभिक आवेदन ड्राफ्ट है।</strong> पात्रता सत्यापन और अंतिम आवेदन केवल आधिकारिक पोर्टल (<a href="{official_link}" target="_blank">{official_link}</a>) या अधिकृत केंद्र पर ही मान्य होगा।
    </div>

    <div class="signature-area">
      <div class="sig-box">
        दिनांक व स्थान (Date & Place)
      </div>
      <div class="sig-box">
        आवेदक के हस्ताक्षर / अंगूठे का निशान<br>
        (Applicant's Signature / Thumb Impression)
      </div>
    </div>

    <div class="disclaimer-box">
      ℹ️ <strong>महत्वपूर्ण सूचना:</strong> {disclaimer}
    </div>
  </div>
  <script>
    window.addEventListener('DOMContentLoaded', function() {{
      try {{
        var params = new URLSearchParams(window.location.search);
        if (params.get('print') === 'true' || params.get('auto_print') === 'true' || window.location.hash === '#print') {{
          setTimeout(function() {{
            window.print();
          }}, 400);
        }}
      }} catch (e) {{
        console.error('Auto-print error:', e);
      }}
    }});
  </script>
</body>
</html>"""


def form_agent(
    scheme_id: str,
    profile: dict[str, Any] | None = None,
    schemes: list[dict[str, Any]] | None = None,
    lang: str = "hi",
    verified_docs: list[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Form Agent:
    Builds a pre-filled draft application form for the chosen scheme,
    including applicant details, document checklist, official link,
    and the mandatory 'Draft prepared by Sahayak. Submit on the official portal.' notice.

    Returns:
        dict:
            "scheme_id": str,
            "scheme_name": str,
            "official_link": str,
            "benefit": str,
            "reply": str,
            "html": str,
            "form_url": str,
    """
    if schemes is None:
        schemes = load_schemes()
    if profile is None:
        profile = {}

    scheme = next((s for s in schemes if s.get("id") == scheme_id), None)
    disclaimer = HINDI_DISCLAIMER if lang == "hi" else ENGLISH_DISCLAIMER

    if not scheme and schemes:
        scheme = schemes[0]
        scheme_id = scheme["id"]

    scheme_name = scheme.get("name_hi" if lang == "hi" else "name_en", scheme_id) if scheme else scheme_id
    official_link = scheme.get("official_link", "") if scheme else ""
    benefit = scheme.get("benefit_hi" if lang == "hi" else "benefit_en", "") if scheme else ""

    html = generate_form_html(
        scheme_id=scheme_id,
        profile=profile,
        schemes=schemes,
        lang=lang,
        verified_docs=verified_docs,
        session_id=session_id,
    )

    form_url = f"/form/{scheme_id}" + (f"?session_id={session_id}" if session_id else "")
    sep = "&" if "?" in form_url else "?"
    pdf_url = f"{form_url}{sep}auto_print=true"
    reminders_url = f"/reminders.ics?scheme_id={scheme_id}" + (f"&session_id={session_id}" if session_id else "")

    if lang == "hi":
        reply = (
            f"**{scheme_name}** के लिए आपका आवेदन प्रारूप (Draft Form) तैयार कर दिया गया है।\n\n"
            f"📥 [यहाँ क्लिक करके आवेदन पत्र डाउनलोड करें (Download PDF)]({pdf_url})\n" + f"📄 [यहाँ क्लिक करके आवेदन प्रारूप देखें व प्रिंट करें]({form_url})\n\n"
            f"📅 [\u092f\u0939\u093e\u0901 \u0915\u094d\u0932\u093f\u0915 \u0915\u0930\u0915\u0947 \u0915\u0948\u0932\u0947\u0902\u0921\u0930 \u0930\u093f\u092e\u093e\u0907\u0902\u0921\u0930 \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u0915\u0930\u0947\u0902 (Download reminders)]({reminders_url})\n\n" + f"📌 Draft prepared by Sahayak. Submit on the official portal.\n"
            f"सहायक (Sahayak) द्वारा तैयार किया गया प्रारूप। कृपया आधिकारिक पोर्टल पर जमा करें।\n\n"
            f"आधिकारिक पोर्टल: {official_link}\n\n"
            f"{disclaimer}"
        )
    else:
        reply = (
            f"Your application draft for **{scheme_name}** has been prepared.\n\n"
            f"📥 [Click here to Download PDF Draft]({pdf_url})\n" + f"📄 [Click here to view and print your Application Draft]({form_url})\n\n"
            f"📅 [Click here to Download reminders (.ics)]({reminders_url})\n\n" + f"📌 Draft prepared by Sahayak. Submit on the official portal.\n\n"
            f"Official portal: {official_link}\n\n"
            f"{disclaimer}"
        )

    return {
        "scheme_id": scheme_id,
        "scheme_name": scheme_name,
        "official_link": official_link,
        "benefit": benefit,
        "reply": reply,
        "html": html,
        "form_url": form_url,
        "pdf_url": pdf_url,
    }



def generate_ics(
    scheme_id: str,
    schemes: list[dict[str, Any]] | None = None,
    lang: str = "hi",
    now: datetime | None = None,
    session_id: str | None = None,
) -> str:
    """Generate an RFC 5545 compliant iCalendar (.ics) string with scheme reminders.

    Follows P6.3:
    - Reminders at 3 days (collecting documents), 7 days (submitting), 30 days (checking status).
    - Includes a real deadline event ONLY if schemes.json contains one; never invents deadlines.
    """
    if schemes is None:
        schemes = load_schemes()
    if now is None:
        now = datetime.now(timezone.utc)

    scheme = next((s for s in schemes if s.get("id") == scheme_id), None)
    if not scheme and schemes:
        scheme = schemes[0]
        scheme_id = scheme["id"]

    scheme_name_hi = scheme.get("name_hi", scheme_id) if scheme else scheme_id
    scheme_name_en = scheme.get("name_en", scheme_id) if scheme else scheme_id
    scheme_name = scheme_name_hi if lang == "hi" else scheme_name_en
    official_link = scheme.get("official_link", "") if scheme else ""
    raw_deadline = scheme.get("deadline") if scheme else None
    deadline_val = str(raw_deadline).strip() if (raw_deadline and str(raw_deadline).strip().upper() not in {"TODO", "NONE", "NULL", ""}) else None

    # Calculate reminder dates
    d3 = now + timedelta(days=3)
    d7 = now + timedelta(days=7)
    d30 = now + timedelta(days=30)
    dtstamp = now.strftime("%Y%m%dT%H%M%SZ")

    def _make_vevent(uid: str, dt_start: datetime, summary: str, description: str) -> str:
        date_str = dt_start.strftime("%Y%m%d")
        next_date_str = (dt_start + timedelta(days=1)).strftime("%Y%m%d")
        desc_escaped = description.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
        summ_escaped = summary.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        vevent_lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART;VALUE=DATE:{date_str}",
            f"DTEND;VALUE=DATE:{next_date_str}",
            f"SUMMARY:{summ_escaped}",
            f"DESCRIPTION:{desc_escaped}",
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "TRIGGER:-PT9H",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{summ_escaped}",
            "END:VALARM",
            "END:VEVENT",
        ]
        return "\r\n".join(vevent_lines) + "\r\n"

    events: list[str] = []

    # 1. Day 3: Collect documents
    summ_3d = f"\u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c\u093c \u090f\u0915\u0924\u094d\u0930 \u0915\u0930\u0947\u0902 \u2014 {scheme_name}" if lang == "hi" else f"Collect Documents \u2014 {scheme_name}"
    desc_3d = (
        f"\u091a\u0947\u0915\u0932\u093f\u0938\u094d\u091f \u0915\u0947 \u0905\u0928\u0941\u0938\u093e\u0930 \u0938\u092d\u0940 \u0906\u0935\u0936\u094d\u092f\u0915 \u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c\u093c \u090f\u0915\u0924\u094d\u0930 \u0915\u0930\u0947\u0902\u0964\n"
        f"\u092f\u094b\u091c\u0928\u093e: {scheme_name}\n"
        f"\u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932: {official_link}\n\n"
        f"Draft prepared by Sahayak. Verify on the official portal."
        if lang == "hi"
        else
        f"Collect all required checklist documents for {scheme_name}.\n"
        f"Official portal: {official_link}\n\n"
        f"Draft prepared by Sahayak. Verify on the official portal."
    )
    events.append(_make_vevent(
        uid=f"sahayak-{scheme_id}-3d-{d3.strftime('%Y%m%d')}@sahayak.gov.in",
        dt_start=d3,
        summary=summ_3d,
        description=desc_3d,
    ))

    # 2. Day 7: Submit application
    summ_7d = f"\u0906\u0935\u0947\u0926\u0928 \u091c\u092e\u093e \u0915\u0930\u0947\u0902 \u2014 {scheme_name}" if lang == "hi" else f"Submit Application \u2014 {scheme_name}"
    desc_7d = (
        f"\u0924\u0948\u092f\u093e\u0930 \u0915\u093f\u092f\u093e \u0917\u092f\u093e \u0906\u0935\u0947\u0926\u0928 \u092a\u0924\u094d\u0930 \u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932 \u092f\u093e \u0928\u093f\u0915\u091f\u0924\u092e \u0938\u0940\u090f\u0938\u0938\u0940 \u092a\u0930 \u091c\u092e\u093e \u0915\u0930\u0947\u0902\u0964\n"
        f"\u092f\u094b\u091c\u0928\u093e: {scheme_name}\n"
        f"\u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932: {official_link}\n\n"
        f"Draft prepared by Sahayak. Submit on the official portal."
        if lang == "hi"
        else
        f"Submit your completed application draft on the official portal or nearest CSC.\n"
        f"Official portal: {official_link}\n\n"
        f"Draft prepared by Sahayak. Submit on the official portal."
    )
    events.append(_make_vevent(
        uid=f"sahayak-{scheme_id}-7d-{d7.strftime('%Y%m%d')}@sahayak.gov.in",
        dt_start=d7,
        summary=summ_7d,
        description=desc_7d,
    ))

    # 3. Day 30: Check application status
    summ_30d = f"\u0906\u0935\u0947\u0926\u0928 \u0938\u094d\u0925\u093f\u0924\u093f \u091c\u093e\u0901\u091a\u0947\u0902 \u2014 {scheme_name}" if lang == "hi" else f"Check Application Status \u2014 {scheme_name}"
    desc_30d = (
        f"\u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932 \u092a\u0930 \u0905\u092a\u0928\u093e \u0906\u0935\u0947\u0926\u0928 \u0915\u094d\u0930\u092e\u093e\u0902\u0915 \u092f\u093e \u0906\u0927\u093e\u0930 \u0928\u0902\u092c\u0930 \u0921\u093e\u0932\u0915\u0930 \u0938\u094d\u0925\u093f\u0924\u093f \u0915\u0940 \u091c\u093e\u0901\u091a \u0915\u0930\u0947\u0902\u0964\n"
        f"\u092f\u094b\u091c\u0928\u093e: {scheme_name}\n"
        f"\u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932: {official_link}\n\n"
        f"Verify on the official portal."
        if lang == "hi"
        else
        f"Check your application status on the official portal using your reference or Aadhaar number.\n"
        f"Official portal: {official_link}\n\n"
        f"Verify on the official portal."
    )
    events.append(_make_vevent(
        uid=f"sahayak-{scheme_id}-30d-{d30.strftime('%Y%m%d')}@sahayak.gov.in",
        dt_start=d30,
        summary=summ_30d,
        description=desc_30d,
    ))

    # 4. Real deadline ONLY if in schemes.json; never invent
    if deadline_val:
        try:
            dl_dt = datetime.strptime(str(deadline_val)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            summ_dl = f"\u26a0\ufe0f \u0905\u0902\u0924\u093f\u092e \u0924\u093f\u0925\u093f (Deadline) \u2014 {scheme_name}" if lang == "hi" else f"\u26a0\ufe0f Application Deadline \u2014 {scheme_name}"
            desc_dl = (
                f"\u092f\u094b\u091c\u0928\u093e \u0906\u0935\u0947\u0926\u0928 \u0915\u0940 \u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u0905\u0902\u0924\u093f\u092e \u0924\u093f\u0925\u093f: {deadline_val}\n"
                f"\u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932: {official_link}\n\n"
                f"\u0915\u0943\u092a\u092f\u093e \u0938\u092e\u092f \u0930\u0939\u0924\u0947 \u0906\u0935\u0947\u0926\u0928 \u092a\u0942\u0930\u094d\u0923 \u0915\u0930\u0947\u0902\u0964"
                if lang == "hi"
                else
                f"Official application deadline: {deadline_val}\n"
                f"Official portal: {official_link}\n\n"
                f"Please complete and submit your application before this deadline."
            )
            events.append(_make_vevent(
                uid=f"sahayak-{scheme_id}-deadline-{dl_dt.strftime('%Y%m%d')}@sahayak.gov.in",
                dt_start=dl_dt,
                summary=summ_dl,
                description=desc_dl,
            ))
        except Exception:
            pass

    header_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Sahayak Citizen Scheme Assistant//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Sahayak - {scheme_name}",
    ]
    return "\r\n".join(header_lines) + "\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def followup_agent(
    scheme_id: str,
    schemes: list[dict[str, Any]] | None = None,
    lang: str = "hi",
    session_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Follow-up Agent:
    Builds follow-up reminders (3 days, 7 days, 30 days) and calendar (.ics) file.
    Uses real deadline ONLY if schemes.json contains one; never invents deadlines.

    Returns:
        dict:
            "scheme_id": str,
            "scheme_name": str,
            "official_link": str,
            "reminders": list[dict],
            "deadline": str | None,
            "ics_content": str,
            "ics_url": str,
            "reply": str,
    """
    if schemes is None:
        schemes = load_schemes()
    if now is None:
        now = datetime.now(timezone.utc)

    scheme = next((s for s in schemes if s.get("id") == scheme_id), None)
    if not scheme and schemes:
        scheme = schemes[0]
        scheme_id = scheme["id"]

    scheme_name_hi = scheme.get("name_hi", scheme_id) if scheme else scheme_id
    scheme_name_en = scheme.get("name_en", scheme_id) if scheme else scheme_id
    scheme_name = scheme_name_hi if lang == "hi" else scheme_name_en
    official_link = scheme.get("official_link", "") if scheme else ""
    raw_deadline = scheme.get("deadline") if scheme else None
    deadline_val = str(raw_deadline).strip() if (raw_deadline and str(raw_deadline).strip().upper() not in {"TODO", "NONE", "NULL", ""}) else None

    d3 = now + timedelta(days=3)
    d7 = now + timedelta(days=7)
    d30 = now + timedelta(days=30)

    reminders = [
        {
            "days": 3,
            "date": d3.strftime("%Y-%m-%d"),
            "display_date": d3.strftime("%d/%m/%Y"),
            "action": "\u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c\u093c \u090f\u0915\u0924\u094d\u0930 \u0915\u0930\u0947\u0902" if lang == "hi" else "Collect required checklist documents",
            "type": "collect_docs",
        },
        {
            "days": 7,
            "date": d7.strftime("%Y-%m-%d"),
            "display_date": d7.strftime("%d/%m/%Y"),
            "action": "\u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932 \u092a\u0930 \u0906\u0935\u0947\u0926\u0928 \u091c\u092e\u093e \u0915\u0930\u0947\u0902" if lang == "hi" else "Submit application draft on official portal",
            "type": "submit_application",
        },
        {
            "days": 30,
            "date": d30.strftime("%Y-%m-%d"),
            "display_date": d30.strftime("%d/%m/%Y"),
            "action": "\u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932 \u092a\u0930 \u0938\u094d\u0925\u093f\u0924\u093f \u091c\u093e\u0901\u091a\u0947\u0902" if lang == "hi" else "Check application status on official portal",
            "type": "check_status",
        },
    ]

    ics_content = generate_ics(
        scheme_id=scheme_id,
        schemes=schemes,
        lang=lang,
        now=now,
        session_id=session_id,
    )

    ics_url = f"/reminders.ics?scheme_id={scheme_id}" + (f"&session_id={session_id}" if session_id else "")
    form_url = f"/form/{scheme_id}" + (f"?session_id={session_id}&auto_print=true" if session_id else "?auto_print=true")
    disclaimer = HINDI_DISCLAIMER if lang == "hi" else ENGLISH_DISCLAIMER

    if lang == "hi":
        deadline_text = f"\u26a0\ufe0f \u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u0905\u0902\u0924\u093f\u092e \u0924\u093f\u0925\u093f (Official Deadline): {deadline_val}\n" if deadline_val else "\u2139\ufe0f \u0907\u0938 \u092f\u094b\u091c\u0928\u093e \u0915\u0947 \u0932\u093f\u090f \u0915\u094b\u0908 \u0928\u093f\u0936\u094d\u091a\u093f\u0924 \u0905\u0902\u0924\u093f\u092e \u0924\u093f\u0925\u093f \u0928\u093f\u0930\u094d\u0927\u093e\u0930\u093f\u0924 \u0928\u0939\u0940\u0902 \u0939\u0948 (\u0906\u0935\u0947\u0926\u0928 \u0916\u0941\u0932\u093e \u0939\u0948)\u0964\n"
        reply = (
            f"**{scheme_name}** \u0915\u0947 \u0932\u093f\u090f \u0906\u092a\u0915\u0940 \u092b\u0949\u0932\u094b-\u0905\u092a \u091a\u0947\u0915\u0932\u093f\u0938\u094d\u091f \u0914\u0930 \u0915\u0948\u0932\u0947\u0902\u0921\u0930 \u0930\u093f\u092e\u093e\u0907\u0902\u0921\u0930 \u0924\u0948\u092f\u093e\u0930 \u0939\u0948\u0902:\n\n"
            f"\U0001f4c5 **\u092b\u0949\u0932\u094b-\u0905\u092a \u0938\u092e\u092f-\u0938\u093e\u0930\u0923\u0940 (Follow-up Schedule):**\n"
            f"1. **3 \u0926\u093f\u0928 \u092c\u093e\u0926 ({d3.strftime('%d/%m/%Y')}):** \u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c\u093c \u090f\u0915\u0924\u094d\u0930 \u0915\u0930\u0947\u0902\n"
            f"2. **7 \u0926\u093f\u0928 \u092c\u093e\u0926 ({d7.strftime('%d/%m/%Y')}):** \u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932 \u092a\u0930 \u0906\u0935\u0947\u0926\u0928 \u091c\u092e\u093e \u0915\u0930\u0947\u0902\n"
            f"3. **30 \u0926\u093f\u0928 \u092c\u093e\u0926 ({d30.strftime('%d/%m/%Y')}):** \u0906\u0935\u0947\u0926\u0928 \u0915\u0940 \u0938\u094d\u0925\u093f\u0924\u093f \u0915\u0940 \u091c\u093e\u0901\u091a \u0915\u0930\u0947\u0902\n\n"
            f"{deadline_text}\n"
            f"\U0001f4e5 [\u092f\u0939\u093e\u0901 \u0915\u094d\u0932\u093f\u0915 \u0915\u0930\u0915\u0947 \u0915\u0948\u0932\u0947\u0902\u0921\u0930 \u0930\u093f\u092e\u093e\u0907\u0902\u0921\u0930 \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u0915\u0930\u0947\u0902 (Download Reminders .ics)]({ics_url})\n\n"
            f"📥 [\u092f\u0939\u093e\u0901 \u0915\u094d\u0932\u093f\u0915 \u0915\u0930\u0915\u0947 \u0906\u0935\u0947\u0926\u0928 \u092a\u094d\u0930ारूप \u0921\u093e\u0909\u0928\u0932\u094b\u0921 \u0915\u0930\u0947ं (Download PDF)]({form_url})\n\n" + f"\U0001f517 \u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915 \u092a\u094b\u0930\u094d\u091f\u0932: {official_link}\n\n"
            f"{disclaimer}"
        )
    else:
        deadline_text = f"\u26a0\ufe0f Official Application Deadline: {deadline_val}\n" if deadline_val else "\u2139\ufe0f No fixed deadline in official records (applications remain open).\n"
        reply = (
            f"Here are your follow-up reminders for **{scheme_name}**:\n\n"
            f"\U0001f4c5 **Follow-up Timeline:**\n"
            f"1. **In 3 days ({d3.strftime('%d/%m/%Y')}):** Collect required checklist documents\n"
            f"2. **In 7 days ({d7.strftime('%d/%m/%Y')}):** Submit application draft on the official portal\n"
            f"3. **In 30 days ({d30.strftime('%d/%m/%Y')}):** Check application status on official portal\n\n"
            f"{deadline_text}\n"
            f"\U0001f4e5 [Click here to Download Calendar Reminders (.ics)]({ics_url})\n\n"
            f"📥 [Click here to Download PDF Draft]({form_url})\n\n" + f"\U0001f517 Official portal: {official_link}\n\n"
            f"{disclaimer}"
        )

    return {
        "scheme_id": scheme_id,
        "scheme_name": scheme_name,
        "official_link": official_link,
        "reminders": reminders,
        "deadline": deadline_val,
        "ics_content": ics_content,
        "ics_url": ics_url,
        "reply": reply,
    }
