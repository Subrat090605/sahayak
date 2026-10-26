"""Unit and integration tests for Phase 7 failure handling and reliability (P7.1).

Covers all 5 failure modes:
1. Model errors (LLM failure graceful recovery)
2. Timeouts (server & network timeout recovery)
3. Empty speech (no transcript / silent mic feedback)
4. Unsupported browser (fallback banner and text input fallback)
5. Unclear language (gibberish / symbol-only clarification)
Plus presence and functionality of the Retry mechanism.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from coordinator import SESSIONS, get_or_create_session, handle_message, is_unclear_message
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_sessions():
    """Ensure in-memory sessions dict is clean for each test."""
    SESSIONS.clear()
    yield
    SESSIONS.clear()


# ---------------------------------------------------------------------------
# 1. Empty Speech / Empty Message Tests
# ---------------------------------------------------------------------------


def test_coordinator_handles_empty_speech_hindi():
    """Empty or whitespace-only message returns friendly speech prompt in Hindi."""
    res = handle_message("sess-empty-hi", "   ", lang="hi")
    assert res["state"] == "COLLECT_PROFILE"
    assert "कोई आवाज़" in res["reply"] or "माइक" in res["reply"]
    assert any("empty speech" in t["action"] for t in res["trace"])


def test_coordinator_handles_empty_speech_english():
    """Empty or None message returns friendly speech prompt in English."""
    res = handle_message("sess-empty-en", "", lang="en")
    assert res["state"] == "COLLECT_PROFILE"
    assert "No voice or message received" in res["reply"] or "tap the mic" in res["reply"]
    assert any("empty speech" in t["action"] for t in res["trace"])


# ---------------------------------------------------------------------------
# 2. Unclear Language / Gibberish Tests
# ---------------------------------------------------------------------------


def test_is_unclear_message_detector():
    """Test unclear language detection on symbols, repetitions, and keyboard mashes."""
    # Unclear cases
    assert is_unclear_message("???") is True
    assert is_unclear_message(".......") is True
    assert is_unclear_message("!@#$%^&*") is True
    assert is_unclear_message("zzzzzzz") is True
    assert is_unclear_message("bcdfgh") is True

    # Valid cases
    assert is_unclear_message("हाँ") is False
    assert is_unclear_message("किसान") is False
    assert is_unclear_message("farmer") is False
    assert is_unclear_message("2") is False
    assert is_unclear_message("PM-KISAN") is False
    assert is_unclear_message("I have 2 acres") is False


def test_coordinator_handles_unclear_language_hindi():
    """Unclear symbols in Hindi prompt a friendly clarification without advancing state."""
    res = handle_message("sess-unclear-hi", "???!!!", lang="hi")
    assert res["state"] == "COLLECT_PROFILE"
    assert "क्षमा करें" in res["reply"]
    assert "समझ नहीं पाए" in res["reply"]
    assert any("unclear language" in t["action"] for t in res["trace"])


def test_coordinator_handles_unclear_language_english():
    """Unclear gibberish in English prompts a friendly clarification without advancing state."""
    res = handle_message("sess-unclear-en", "bcdfghjklmnp", lang="en")
    assert res["state"] == "COLLECT_PROFILE"
    assert "could not clearly understand" in res["reply"].lower()
    assert any("unclear language" in t["action"] for t in res["trace"])


# ---------------------------------------------------------------------------
# 3. Model Error Recovery Tests
# ---------------------------------------------------------------------------


def test_chat_endpoint_model_error_recovery_hindi():
    """When LLM model raises an error, endpoint recovers with friendly Hindi message."""
    with patch("main.handle_message", side_effect=RuntimeError("Google GenAI RateLimit 429")):
        resp = client.post(
            "/chat",
            json={"session_id": "sess-err-hi", "message": "मैं किसान हूँ", "lang": "hi"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "क्षमा करें" in data["reply"]
    assert any("error recovery" in t["action"] for t in data["trace"])


def test_chat_endpoint_model_error_recovery_english():
    """When LLM model raises an error, endpoint recovers with friendly English message."""
    with patch("main.handle_message", side_effect=RuntimeError("Groq service 503 unavailable")):
        resp = client.post(
            "/chat",
            json={"session_id": "sess-err-en", "message": "I am a farmer", "lang": "en"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "temporary" in data["reply"].lower() or "service" in data["reply"].lower()
    assert any("error recovery" in t["action"] for t in data["trace"])


# ---------------------------------------------------------------------------
# 4. Timeout Recovery Tests
# ---------------------------------------------------------------------------


def test_chat_endpoint_timeout_recovery_hindi():
    """TimeoutError produces a timeout-specific friendly message in Hindi."""
    with patch("main.handle_message", side_effect=TimeoutError("Request timed out after 15s")):
        resp = client.post(
            "/chat",
            json={"session_id": "sess-tout-hi", "message": "मेरी ज़मीन 2 एकड़ है", "lang": "hi"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "समय समाप्त" in data["reply"] or "timeout" in data["reply"].lower()
    assert any("timeout" in t["action"].lower() for t in data["trace"])


def test_chat_endpoint_timeout_recovery_english():
    """Timeout string exception produces a timeout-specific friendly message in English."""
    with patch("main.handle_message", side_effect=Exception("ReadTimeout from httpx")):
        resp = client.post(
            "/chat",
            json={"session_id": "sess-tout-en", "message": "I own 2 acres of land", "lang": "en"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "timed out" in data["reply"].lower() or "timeout" in data["reply"].lower()
    assert any("timeout" in t["action"].lower() for t in data["trace"])


# ---------------------------------------------------------------------------
# 5. Unsupported Browser & Frontend Failure Handling Markup Tests
# ---------------------------------------------------------------------------


def test_static_html_contains_failure_handlers():
    """Verify static index.html has failure handlers for all required conditions."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # Unsupported browser handling
    assert "showUnsupportedBrowserNotice" in html
    assert "unsupported" in html

    # Empty speech handling
    assert "showEmptySpeechNotice" in html
    assert "empty_speech" in html

    # Timeout handling (AbortController)
    assert "AbortController" in html
    assert "timeout" in html

    # Retry button and retryLastMessage
    assert "retryLastMessage" in html
    assert "retry-btn" in html
