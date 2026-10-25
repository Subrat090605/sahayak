"""Tests for main.py (FastAPI endpoints: /health and /chat)."""

from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_endpoint_success():
    mock_coord_result = {
        "reply": "आप क्या काम करते हैं?",
        "lang": "hi",
        "state": "COLLECT_PROFILE",
        "matches": [],
        "trace": [{"agent": "eligibility", "action": "asking occupation", "ms": 50}],
    }

    with patch("main.handle_message", return_value=mock_coord_result):
        response = client.post(
            "/chat",
            json={"session_id": "sess-api-1", "message": "नमस्ते", "lang": "hi"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "आप क्या काम करते हैं?"
    assert data["lang"] == "hi"
    assert data["state"] == "COLLECT_PROFILE"
    assert isinstance(data["matches"], list)
    assert len(data["trace"]) == 1
    assert data["trace"][0]["agent"] == "eligibility"


def test_chat_endpoint_graceful_error_recovery():
    """If model or coordinator fails, endpoint degrades to friendly message without crashing."""
    with patch("main.handle_message", side_effect=RuntimeError("LLM API overloaded")):
        response = client.post(
            "/chat",
            json={"session_id": "sess-err", "message": "I am a farmer", "lang": "en"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "temporary" in data["reply"].lower() or "service" in data["reply"].lower()
    assert data["lang"] == "en"
    assert data["state"] == "COLLECT_PROFILE"
    assert any("error recovery" in t["action"] for t in data["trace"])
