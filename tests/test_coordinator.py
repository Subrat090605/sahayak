"""Unit tests for coordinator.py (session store, state machine, trace, and reset)."""

from unittest.mock import patch
import pytest
from coordinator import SESSIONS, get_or_create_session, handle_message, reset_session


@pytest.fixture(autouse=True)
def clean_sessions():
    """Ensure in-memory sessions dict is clean for every test."""
    SESSIONS.clear()
    yield
    SESSIONS.clear()


def test_session_creation_and_reset():
    sess = get_or_create_session("sess-1", lang="hi")
    assert sess["session_id"] == "sess-1"
    assert sess["state"] == "COLLECT_PROFILE"
    assert sess["profile"] == {}

    # Mutate session
    sess["profile"]["occupation"] = "farmer"
    sess["state"] = "MATCH"

    # Reset session
    reset = reset_session("sess-1", lang="hi")
    assert reset["state"] == "COLLECT_PROFILE"
    assert reset["profile"] == {}


def test_coordinator_handles_start_over():
    sess = get_or_create_session("sess-test", lang="en")
    sess["profile"] = {"occupation": "student"}
    sess["state"] = "MATCH"

    res = handle_message("sess-test", "start over", lang="en")

    assert res["state"] == "COLLECT_PROFILE"
    assert SESSIONS["sess-test"]["profile"] == {}
    assert len(res["trace"]) > 0
    assert res["trace"][0]["agent"] == "coordinator"
    assert "reset" in res["trace"][0]["action"].lower()
    assert "reset" in res["reply"].lower()


def test_coordinator_turn_by_turn_state_machine():
    session_id = "test-farmer-multi-turn"

    # Turn 1: Farmer mentions occupation and land acres, but income is missing
    mock_extracted_turn1 = {
        "extracted_fields": {"occupation": "farmer", "land_acres": 2.0, "district": "Unnao"},
        "detected_language": "en",
    }

    with patch("agents.generate_json", return_value=mock_extracted_turn1):
        turn1 = handle_message(session_id, "I am a farmer in Unnao with two acres", lang="en")

    assert turn1["state"] == "COLLECT_PROFILE"
    assert turn1["matches"] != []
    # Trace contains profile and eligibility
    agents_in_trace = [t["agent"] for t in turn1["trace"]]
    assert "profile" in agents_in_trace
    assert "eligibility" in agents_in_trace
    assert all("ms" in t for t in turn1["trace"])

    # Turn 2: Farmer provides missing income
    mock_extracted_turn2 = {
        "extracted_fields": {"annual_income": 80000},
        "detected_language": "en",
    }
    mock_explain = (
        "You are eligible for PM-KISAN and PM-JAY.\n"
        "PM-KISAN: https://pmkisan.gov.in\n"
        "Please verify all rules and details on the official portal."
    )

    with patch("agents.generate_json", return_value=mock_extracted_turn2):
        with patch("agents.generate_text", return_value=mock_explain):
            turn2 = handle_message(session_id, "My annual income is 80000 rupees", lang="en")

    # State transitions to MATCH
    assert turn2["state"] == "MATCH"
    assert "https://pmkisan.gov.in" in turn2["reply"]
    eligible_ids = [m["scheme_id"] for m in turn2["matches"] if m["status"] == "eligible"]
    assert "pm-kisan" in eligible_ids
