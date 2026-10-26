"""Unit and integration tests for Follow-up Agent and /reminders.ics endpoint."""

from datetime import datetime, timezone
from fastapi.testclient import TestClient

from agents import followup_agent, generate_ics
from coordinator import SESSIONS, get_or_create_session, handle_message, reset_session
from eligibility import load_schemes
from main import app

client = TestClient(app)


def test_generate_ics_three_standard_reminders():
    """Verify generate_ics produces RFC 5545 calendar with 3, 7, 30 day reminders."""
    schemes = load_schemes()
    fixed_now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)

    ics = generate_ics("pm-kisan", schemes=schemes, lang="hi", now=fixed_now)

    # 1. RFC 5545 structure
    assert "BEGIN:VCALENDAR" in ics
    assert "VERSION:2.0" in ics
    assert "PRODID:-//Sahayak" in ics
    assert "CALSCALE:GREGORIAN" in ics
    assert "METHOD:PUBLISH" in ics
    assert "END:VCALENDAR" in ics

    # 2. Exactly 3 events (no deadline in schemes.json for pm-kisan)
    assert ics.count("BEGIN:VEVENT") == 3
    assert ics.count("END:VEVENT") == 3

    # 3. Day 3: Oct 4, 2026
    assert "DTSTART;VALUE=DATE:20261004" in ics

    # 4. Day 7: Oct 8, 2026
    assert "DTSTART;VALUE=DATE:20261008" in ics

    # 5. Day 30: Oct 31, 2026
    assert "DTSTART;VALUE=DATE:20261031" in ics

    # 6. Official portal link in descriptions
    assert "https://pmkisan.gov.in" in ics
    assert "Draft prepared by Sahayak. Verify on the official portal." in ics


def test_generate_ics_respects_real_deadline_only():
    """Verify a deadline event is created ONLY if schemes.json contains a real deadline,
    and is NEVER invented when missing.
    """
    fixed_now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Case A: Scheme with NO deadline (default pm-kisan)
    ics_no_dl = generate_ics("pm-kisan", now=fixed_now)
    assert ics_no_dl.count("BEGIN:VEVENT") == 3
    assert "Deadline" not in ics_no_dl

    # Case B: Scheme WITH a real deadline
    mock_schemes = [{
        "id": "state-student-merit",
        "name_en": "State Student Merit Scheme",
        "name_hi": "राज्य छात्र मेरिट योजना",
        "official_link": "https://scholarships.gov.in",
        "deadline": "2026-11-30",
    }]

    ics_with_dl = generate_ics("state-student-merit", schemes=mock_schemes, now=fixed_now, lang="en")
    # 3 standard reminders + 1 real deadline event = 4 events
    assert ics_with_dl.count("BEGIN:VEVENT") == 4
    assert "DTSTART;VALUE=DATE:20261130" in ics_with_dl
    assert "Application Deadline" in ics_with_dl


def test_followup_agent_returns_structured_dictionary():
    """Verify followup_agent returns required fields, schedule list, and reply."""
    schemes = load_schemes()
    fixed_now = datetime(2026, 10, 15, 9, 0, 0, tzinfo=timezone.utc)

    res = followup_agent(
        scheme_id="pm-jay",
        schemes=schemes,
        lang="hi",
        session_id="sess-rem-1",
        now=fixed_now,
    )

    assert res["scheme_id"] == "pm-jay"
    assert "https://pmjay.gov.in" in res["official_link"]
    assert len(res["reminders"]) == 3

    assert res["reminders"][0]["days"] == 3
    assert res["reminders"][0]["date"] == "2026-10-18"
    assert res["reminders"][1]["days"] == 7
    assert res["reminders"][1]["date"] == "2026-10-22"
    assert res["reminders"][2]["days"] == 30
    assert res["reminders"][2]["date"] == "2026-11-14"

    assert res["deadline"] is None
    assert "/reminders.ics?scheme_id=pm-jay&session_id=sess-rem-1" in res["ics_url"]

    # Reply contains dates, download link, and official portal
    assert "2026" in res["reply"]
    assert res["ics_url"] in res["reply"]
    assert "https://pmjay.gov.in" in res["reply"]


def test_reminders_ics_endpoint_download():
    """Test GET /reminders.ics endpoint returns valid text/calendar attachment."""
    response = client.get("/reminders.ics?scheme_id=pm-kisan")
    assert response.status_code == 200
    assert "text/calendar" in response.headers["content-type"]
    assert 'attachment; filename="reminders_pm-kisan.ics"' in response.headers["content-disposition"]

    body = response.text
    assert "BEGIN:VCALENDAR" in body
    assert "END:VCALENDAR" in body
    assert body.count("BEGIN:VEVENT") == 3
    assert "https://pmkisan.gov.in" in body


def test_reminders_scheme_alias_route():
    """Test GET /reminders/{scheme_id}.ics alias route."""
    response = client.get("/reminders/pm-ujjwala.ics")
    assert response.status_code == 200
    assert "text/calendar" in response.headers["content-type"]
    assert "pm-ujjwala" in response.headers["content-disposition"]
    assert "BEGIN:VCALENDAR" in response.text


def test_coordinator_handles_reminders_intent():
    """Test coordinator handles user request for reminders and transitions state."""
    sess_id = "sess-rem-coord"
    reset_session(sess_id, lang="hi")
    sess = get_or_create_session(sess_id, lang="hi")
    sess["state"] = "FORM"
    sess["selected_scheme"] = "pm-kisan"

    # User asks for reminders in English
    res = handle_message(sess_id, "please send me calendar reminders for this scheme")

    assert res["state"] == "REMINDERS"
    assert any(t["agent"] == "followup" for t in res["trace"])
    assert "/reminders.ics" in res["reply"]
    assert "https://pmkisan.gov.in" in res["reply"]


def test_coordinator_handles_reminders_intent_hindi():
    """Test coordinator handles user request for reminders in Hindi."""
    sess_id = "sess-rem-coord-hi"
    reset_session(sess_id, lang="hi")
    sess = get_or_create_session(sess_id, lang="hi")
    sess["state"] = "FORM"
    sess["selected_scheme"] = "pm-kisan"

    res = handle_message(sess_id, "मुज्हे इस योजना का कैलेंडर रिमाइंडर चाहिए")

    assert res["state"] == "REMINDERS"
    assert any(t["agent"] == "followup" for t in res["trace"])
    assert "/reminders.ics" in res["reply"]
    assert "https://pmkisan.gov.in" in res["reply"]


def test_static_index_contains_reminders_button():
    """Verify static/index.html includes Reminders button on scheme cards and function."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "btn_reminders_" in html
    assert "downloadRemindersIcs" in html
    assert "reminders.ics" in html
    assert ".chat-ics-btn" in html


def test_chat_flow_wires_both_outputs_after_scheme_picked():
    """Verify both Download PDF and Download reminders are wired into chat flow
    when a user picks a scheme (P6.4).
    """
    sess_id = "sess-pick-scheme-both-outputs"
    reset_session(sess_id, lang="en")
    sess = get_or_create_session(sess_id, lang="en")
    sess["state"] = "MATCH"
    sess["profile"] = {"name": "Ramesh", "occupation": "farmer", "land_acres": 2.0}

    # User picks PM-KISAN
    res = handle_message(sess_id, "Tell me about PM-KISAN", lang="en")

    assert res["state"] == "DOCUMENTS"
    # Output 1: Download PDF
    assert "Download PDF" in res["reply"]
    assert "/form/pm-kisan" in res["reply"]
    # Output 2: Download reminders
    assert "Download reminders" in res["reply"]
    assert "/reminders.ics" in res["reply"]
    # Scheme details / Checklist
    assert "https://pmkisan.gov.in" in res["reply"]


def test_chat_flow_wires_both_outputs_hindi():
    """Verify both outputs are wired into Hindi chat flow after user picks scheme."""
    sess_id = "sess-pick-scheme-hi"
    reset_session(sess_id, lang="hi")
    sess = get_or_create_session(sess_id, lang="hi")
    sess["state"] = "MATCH"
    sess["profile"] = {"name": "रमेश", "occupation": "farmer", "land_acres": 2.0}

    # User picks PM-KISAN in Hindi
    res = handle_message(sess_id, "मुज्हे पीएम-किसान चुनना है", lang="hi")

    assert res["state"] == "DOCUMENTS"
    assert "/form/pm-kisan" in res["reply"]
    assert "Download PDF" in res["reply"]
    assert "/reminders.ics" in res["reply"]
    assert "Download reminders" in res["reply"]


def test_static_index_has_download_reminders_exact_button():
    """Verify static/index.html includes exact 'Download reminders' button text."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "Download reminders" in html
    assert "btn_reminders_" in html
    assert "downloadRemindersIcs" in html
