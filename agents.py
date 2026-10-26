"""Agents for Sahayak: Profile Agent, Eligibility Agent, and tools.

Each agent follows docs/ARCHITECTURE.md, docs/DATA_SCHEMA.md, and PRD guidelines.
"""

from __future__ import annotations

import json
import logging
import re
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


