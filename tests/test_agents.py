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


