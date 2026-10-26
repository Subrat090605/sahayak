"""Unit and integration tests for Demo Mode and /demo/load endpoint (P7.2)."""

import pytest
from fastapi.testclient import TestClient

from coordinator import SESSIONS, get_or_create_session
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_sessions():
    """Ensure in-memory sessions are cleared for each test."""
    SESSIONS.clear()
    yield
    SESSIONS.clear()


def test_demo_load_post_default():
    """POST /demo/load loads standard Unnao farmer profile and evaluates eligibility."""
    resp = client.post("/demo/load", json={"lang": "hi"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "ok"
    assert data["session_id"].startswith("demo-")
    assert data["profile"]["occupation"] == "farmer"
    assert data["profile"]["district"] == "Unnao"
    assert data["profile"]["land_acres"] == 2.0
    assert data["profile"]["annual_income"] == 80000
    assert data["state"] == "MATCH"

    # Evaluated matches should contain pm-kisan marked eligible
    matched_ids = [m["scheme_id"] for m in data["matches"] if m.get("status") == "eligible"]
    assert "pm-kisan" in matched_ids

    # Scripted demo steps
    assert len(data["demo_steps"]) == 3
    assert any("उन्नाव" in s["message_hi"] for s in data["demo_steps"])
    assert any("80,000" in s["message_hi"] for s in data["demo_steps"])
    assert any("दस्तावेज़" in s["message_hi"] for s in data["demo_steps"])

    # Trace contains loading and evaluation actions
    assert len(data["trace"]) >= 2
    assert any("farmer profile" in t["action"] for t in data["trace"])


def test_demo_load_post_custom_session():
    """POST /demo/load updates an existing session and supports profile overrides."""
    sess = get_or_create_session("sess-custom-demo", lang="en")
    assert sess["profile"] == {}

    resp = client.post(
        "/demo/load",
        json={
            "session_id": "sess-custom-demo",
            "lang": "en",
            "profile": {"name": "Ramesh Singh", "age": 45},
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["session_id"] == "sess-custom-demo"
    assert data["profile"]["name"] == "Ramesh Singh"
    assert data["profile"]["occupation"] == "farmer"
    assert data["profile"]["age"] == 45
    assert "pm-kisan" in [m["scheme_id"] for m in data["matches"]]

    # Verify session store updated
    assert SESSIONS["sess-custom-demo"]["profile"]["name"] == "Ramesh Singh"
    assert SESSIONS["sess-custom-demo"]["selected_scheme"] == "pm-kisan"


def test_demo_load_get_endpoint():
    """GET /demo/load alias functions correctly with query parameters."""
    resp = client.get("/demo/load?lang=en")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["profile"]["occupation"] == "farmer"
    assert "pm-kisan" in [m["scheme_id"] for m in data["matches"]]
    assert len(data["demo_steps"]) == 3


def test_demo_mode_static_html_components():
    """Verify static index.html has demo mode button, trigger, and playback functions."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    assert "btnDemo" in html
    assert "playDemoMode" in html
    assert "/demo/load" in html
    assert "demo-banner-box" in html
    assert "demo-completion-card" in html
    assert "demoBtnLabel" in html
