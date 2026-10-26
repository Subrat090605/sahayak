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


def test_upload_doc_endpoint_success():
    """Test successful document image upload and verification."""
    mock_verify_res = {
        "doc_type": "aadhaar",
        "matches_checklist": True,
        "matched_doc_id": "aadhaar",
        "readable": True,
        "masked_id": "XXXX-XXXX-4321",
        "notes": "Valid Aadhaar Card identified. Please verify all rules on the official portal.",
    }

    dummy_image = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfakeimagebytes"
    with patch("main.verify_document_image", return_value=mock_verify_res) as mock_verify:
        response = client.post(
            "/upload-doc",
            files={"file": ("fake_aadhaar.png", dummy_image, "image/png")},
            data={"session_id": "sess-doc-1", "scheme_id": "pm-kisan", "lang": "hi"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["doc_type"] == "aadhaar"
    assert data["matches_checklist"] is True
    assert data["matched_doc_id"] == "aadhaar"
    assert data["readable"] is True
    assert data["masked_id"] == "XXXX-XXXX-4321"
    assert "official portal" in data["notes"].lower() or "पोर्टल" in data["notes"]
    assert mock_verify.called


def test_upload_doc_endpoint_error_recovery():
    """Endpoint catches unexpected failures and returns friendly fallback without crashing."""
    dummy_image = b"fakeimage"
    with patch("main.verify_document_image", side_effect=RuntimeError("Vision service timeout")):
        response = client.post(
            "/upload-doc",
            files={"file": ("doc.jpg", dummy_image, "image/jpeg")},
            data={"session_id": "sess-err-2", "lang": "en"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["doc_type"] == "unknown"
    assert data["matches_checklist"] is False
    assert data["readable"] is False
    assert "error" in data["notes"].lower() or "sorry" in data["notes"].lower()

