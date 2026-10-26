"""Unit tests for agents.py (Profile Agent)."""

from unittest.mock import patch
import pytest
from agents import profile_agent, _sanitize_profile_fields


def test_sanitize_profile_fields_filters_unknown_and_casts_types():
    raw_data = {
        "name": "Ramesh Kumar",
        "age": "42",
        "occupation": "Farmer",
        "land_acres": "2.5",
        "annual_income": "90,000",
        "has_lpg_connection": "false",
        "bpl_household": True,
        "favorite_movie": "Sholay",  # unknown field
        "blood_group": "B+",         # unknown field
    }

    clean = _sanitize_profile_fields(raw_data)

    assert clean["name"] == "Ramesh Kumar"
    assert clean["age"] == 42
    assert clean["occupation"] == "farmer"
    assert clean["land_acres"] == 2.5
    assert clean["annual_income"] == 90000
    assert clean["has_lpg_connection"] is False
    assert clean["bpl_household"] is True
    assert "favorite_movie" not in clean
    assert "blood_group" not in clean


def test_profile_agent_merges_existing_profile():
    existing = {"state": "Uttar Pradesh", "district": "Unnao"}

    mock_llm_response = {
        "extracted_fields": {
            "occupation": "farmer",
            "land_acres": 2.0,
        },
        "detected_language": "hi",
    }

    with patch("agents.generate_json", return_value=mock_llm_response):
        res = profile_agent("मेरे पास दो एकड़ ज़मीन है", existing_profile=existing)

    assert res["lang"] == "hi"
    assert res["profile"]["state"] == "Uttar Pradesh"
    assert res["profile"]["district"] == "Unnao"
    assert res["profile"]["occupation"] == "farmer"
    assert res["profile"]["land_acres"] == 2.0
    assert res["extracted"]["land_acres"] == 2.0


def test_profile_agent_detects_english_language():
    mock_llm_response = {
        "extracted_fields": {
            "age": 21,
            "occupation": "student",
        },
        "detected_language": "en",
    }

    with patch("agents.generate_json", return_value=mock_llm_response):
        res = profile_agent("I am a 21 year old student", existing_profile={})

    assert res["lang"] == "en"
    assert res["profile"]["age"] == 21
    assert res["profile"]["occupation"] == "student"


def test_profile_agent_handles_llm_failure_gracefully():
    with patch("agents.generate_json", side_effect=Exception("API connection timeout")):
        res = profile_agent("नमस्ते", existing_profile={"occupation": "farmer"})

    # Graceful degradation without crashing
    assert res["lang"] == "hi"
    assert res["profile"] == {"occupation": "farmer"}
    assert res["extracted"] == {}


def test_get_missing_fields_ordered_by_importance():
    from eligibility import load_schemes
    from agents import get_missing_fields

    schemes = load_schemes()
    # Empty profile should prioritize occupation
    missing = get_missing_fields({}, schemes)
    assert len(missing) > 0
    assert missing[0] == "occupation"

    # Profile with occupation: farmer should prioritize annual_income or land_acres
    missing_farmer = get_missing_fields({"occupation": "farmer"}, schemes)
    assert "occupation" not in missing_farmer
    assert "land_acres" in missing_farmer


def test_eligibility_agent_asks_one_question_when_fields_missing():
    from eligibility import load_schemes
    from agents import eligibility_agent

    schemes = load_schemes()
    res = eligibility_agent({"occupation": "farmer"}, schemes=schemes, lang="hi")

    assert res["needs_follow_up"] is True
    assert res["missing_field"] in {"annual_income", "land_acres"}
    assert len(res["reply"]) > 0
    # Must only ask one question (not multiple questions joined together)
    assert res["reply"].count("?") <= 1


def test_eligibility_agent_explains_results_with_portal_link_and_disclaimer():
    from eligibility import load_schemes
    from agents import eligibility_agent, HINDI_DISCLAIMER

    schemes = load_schemes()
    complete_farmer_profile = {
        "name": "Ramesh Kumar",
        "occupation": "farmer",
        "land_acres": 2.0,
        "annual_income": 90000,
        "gender": "male",
        "age": 42,
        "bpl_household": False,
        "has_lpg_connection": True,
    }

    mock_llm_reply = (
        "आप पीएम-किसान और आयुष्मान भारत के लिए पात्र हैं।\n"
        "पीएम-किसान: https://pmkisan.gov.in\n"
        "आयुष्मान भारत: https://pmjay.gov.in\n\n"
        f"{HINDI_DISCLAIMER}"
    )

    with patch("agents.generate_text", return_value=mock_llm_reply):
        res = eligibility_agent(complete_farmer_profile, schemes=schemes, lang="hi")

    assert res["needs_follow_up"] is False
    assert res["missing_field"] is None
    assert "https://pmkisan.gov.in" in res["reply"]
    assert HINDI_DISCLAIMER in res["reply"]


def test_eligibility_agent_guardrail_system_prompt_and_enforcement():
    """Verify guardrails: system prompt contains strict instructions and links/disclaimer are enforced."""
    from eligibility import load_schemes
    from agents import eligibility_agent, ELIGIBILITY_SYSTEM_PROMPT, ENGLISH_DISCLAIMER

    schemes = load_schemes()
    complete_profile = {
        "name": "Ramesh",
        "occupation": "farmer",
        "land_acres": 2.0,
        "annual_income": 90000,
        "gender": "male",
        "age": 42,
        "bpl_household": False,
        "has_lpg_connection": True,
    }

    # Verify ELIGIBILITY_SYSTEM_PROMPT text has required guardrail clauses
    assert "schemes.json" in ELIGIBILITY_SYSTEM_PROMPT
    assert "NEVER invent" in ELIGIBILITY_SYSTEM_PROMPT
    assert "official link" in ELIGIBILITY_SYSTEM_PROMPT.lower()
    assert "verify on the official portal" in ELIGIBILITY_SYSTEM_PROMPT.lower()

    # Mocked model omits link and disclaimer
    raw_mock_output = "You qualify for PM-KISAN with 6000 rupees benefit."

    with patch("agents.generate_text", return_value=raw_mock_output) as mock_gen:
        res = eligibility_agent(complete_profile, schemes=schemes, lang="en")

        # Verify generate_text was called with system_prompt containing guardrails
        _, kwargs = mock_gen.call_args
        assert kwargs.get("system_prompt") == ELIGIBILITY_SYSTEM_PROMPT

    # Agent guardrails must guarantee official link and disclaimer exist in final output
    assert "https://pmkisan.gov.in" in res["reply"]
    assert ENGLISH_DISCLAIMER in res["reply"]


def test_document_agent_returns_checklist_pm_kisan_hindi():
    """Verify document_agent returns verified checklist for PM-KISAN in Hindi."""
    from eligibility import load_schemes
    from agents import document_agent, HINDI_DISCLAIMER

    schemes = load_schemes()
    mock_reply = (
        "पीएम-किसान के लिए आवश्यक दस्तावेज़:\n"
        "1. आधार कार्ड: UIDAI पोर्टल या निकटतम आधार सेवा केंद्र / जन सेवा केंद्र\n"
        "2. भूमि स्वामित्व रिकॉर्ड (खसरा / खतौनी): राज्य राजस्व विभाग का पोर्टल या स्थानीय तहसील\n"
        "3. आधार से जुड़ा बैंक खाता पासबुक: आपकी स्थानीय बैंक शाखा\n\n"
        "https://pmkisan.gov.in\n"
        f"{HINDI_DISCLAIMER}"
    )

    with patch("agents.generate_text", return_value=mock_reply):
        res = document_agent("pm-kisan", schemes=schemes, lang="hi")

    assert res["scheme_id"] == "pm-kisan"
    assert "पीएम-किसान" in res["scheme_name"]
    assert res["official_link"] == "https://pmkisan.gov.in"
    assert len(res["documents"]) == 3

    doc_ids = [d["id"] for d in res["documents"]]
    assert doc_ids == ["aadhaar", "land_record", "bank_passbook"]
    assert "आधार कार्ड" in res["documents"][0]["name"]
    assert "UIDAI" in res["documents"][0]["where_to_get"]
    assert res["documents"][0]["checked"] is False

    assert "https://pmkisan.gov.in" in res["reply"]
    assert HINDI_DISCLAIMER in res["reply"]


def test_document_agent_returns_checklist_pm_jay_english():
    """Verify document_agent returns verified checklist for PM-JAY in English."""
    from eligibility import load_schemes
    from agents import document_agent, ENGLISH_DISCLAIMER

    schemes = load_schemes()
    mock_reply = (
        "Required documents for Ayushman Bharat PM-JAY:\n"
        "1. Aadhaar Card: UIDAI portal\n"
        "2. Ration Card / BPL Card / Family ID: State Food & Civil Supplies Department portal\n\n"
        "https://pmjay.gov.in\n"
        f"{ENGLISH_DISCLAIMER}"
    )

    with patch("agents.generate_text", return_value=mock_reply):
        res = document_agent("pm-jay", schemes=schemes, lang="en")

    assert res["scheme_id"] == "pm-jay"
    assert "Ayushman Bharat" in res["scheme_name"]
    assert res["official_link"] == "https://pmjay.gov.in"
    assert len(res["documents"]) == 2

    doc_ids = [d["id"] for d in res["documents"]]
    assert doc_ids == ["aadhaar", "ration_card"]
    assert "Aadhaar Card" in res["documents"][0]["name"]
    assert "Ration Card" in res["documents"][1]["name"]

    assert "https://pmjay.gov.in" in res["reply"]
    assert ENGLISH_DISCLAIMER in res["reply"]


def test_document_agent_guardrails_and_system_prompt():
    """Verify document agent system prompt guardrails and enforcement of link and disclaimer."""
    from eligibility import load_schemes
    from agents import document_agent, DOCUMENT_SYSTEM_PROMPT, ENGLISH_DISCLAIMER

    schemes = load_schemes()
    assert "checklist" in DOCUMENT_SYSTEM_PROMPT.lower()
    assert "never invent" in DOCUMENT_SYSTEM_PROMPT.lower()
    assert "official portal link" in DOCUMENT_SYSTEM_PROMPT.lower()
    assert "verify on the official portal" in DOCUMENT_SYSTEM_PROMPT.lower()

    # If the LLM omits the link and disclaimer
    mock_raw_output = "Here are your documents: 1. Aadhaar Card 2. Land Record"
    with patch("agents.generate_text", return_value=mock_raw_output) as mock_gen:
        res = document_agent("pm-kisan", schemes=schemes, lang="en")

        _, kwargs = mock_gen.call_args
        assert kwargs.get("system_prompt") == DOCUMENT_SYSTEM_PROMPT

    # Guardrails must have enforced the inclusion of official link and disclaimer
    assert "https://pmkisan.gov.in" in res["reply"]
    assert ENGLISH_DISCLAIMER in res["reply"]


def test_document_agent_unknown_scheme():
    """Verify document_agent handles non-existent scheme gracefully."""
    from eligibility import load_schemes
    from agents import document_agent

    schemes = load_schemes()
    res = document_agent("non-existent-scheme", schemes=schemes, lang="hi")
    assert res["documents"] == []
    assert "नहीं मिली" in res["reply"]


def test_mask_id_number():
    """Verify ID masking strictly exposes at most the last 4 digits."""
    from agents import mask_id_number

    assert mask_id_number("123456789012") == "XXXX-XXXX-9012"
    assert mask_id_number("1234 5678 9012") == "XXXX-XXXX-9012"
    assert mask_id_number("1234-5678-9012") == "XXXX-XXXX-9012"
    assert mask_id_number("987654321098") == "XXXX-XXXX-1098"
    assert mask_id_number("98765432109876") == "XXXXXXXXXX9876"
    assert mask_id_number("XXXX-XXXX-4321") == "XXXX-XXXX-4321"
    assert mask_id_number("1234") == "1234"
    assert mask_id_number(None) is None


def test_mask_sensitive_text():
    """Verify sensitive ID numbers are masked inside free text."""
    from agents import mask_sensitive_text

    text = "Citizen Aadhaar is 9876 5432 1098 and bank account is 123456789012."
    masked = mask_sensitive_text(text)
    assert "9876 5432" not in masked
    assert "XXXX-XXXX-1098" in masked
    assert "12345678" not in masked
    assert "9012" in masked


def test_verify_document_image_aadhaar_success():
    """Verify verify_document_image correctly matches PM-KISAN checklist with masked ID."""
    from agents import verify_document_image

    mock_vision_output = """```json
    {
      "doc_type": "aadhaar",
      "readable": true,
      "masked_id": "XXXX-XXXX-5566",
      "notes": "Clear Aadhaar card with legible name and details."
    }
    ```"""

    dummy_image = b"fake-png-bytes"
    with patch("agents.describe_image", return_value=mock_vision_output):
        res = verify_document_image(dummy_image, mime_type="image/png", scheme_id="pm-kisan", lang="en")

    assert res["doc_type"] == "aadhaar"
    assert res["matches_checklist"] is True
    assert res["matched_doc_id"] == "aadhaar"
    assert res["readable"] is True
    assert res["masked_id"] == "XXXX-XXXX-5566"
    assert "official portal" in res["notes"].lower()


def test_verify_document_image_unmatched_checklist():
    """Verify a valid document not needed by the scheme is flagged matches_checklist=False."""
    from agents import verify_document_image

    mock_vision_output = '{"doc_type": "marksheet", "readable": true, "masked_id": null, "notes": "Class 10 marksheet"}'

    dummy_image = b"fake-jpeg-bytes"
    with patch("agents.describe_image", return_value=mock_vision_output):
        res = verify_document_image(dummy_image, mime_type="image/jpeg", scheme_id="pm-kisan", lang="hi")

    assert res["doc_type"] == "marksheet"
    assert res["matches_checklist"] is False
    assert res["matched_doc_id"] is None



