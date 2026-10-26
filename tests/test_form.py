"""Unit and integration tests for Form Agent and /form endpoints."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from agents import form_agent, generate_form_html
from coordinator import SESSIONS, get_or_create_session, handle_message, reset_session
from eligibility import load_schemes
from main import app

client = TestClient(app)


def test_generate_form_html_contains_all_mandated_elements():
    """Verify generate_form_html contains user details, scheme name, document checklist,
    official link, the exact note, A4 print CSS, and Devanagari font.
    """
    schemes = load_schemes()
    profile = {
        "name": "रमेश कुमार",
        "age": 42,
        "gender": "male",
        "state": "उत्तर प्रदेश",
        "district": "उन्नाव",
        "occupation": "farmer",
        "land_acres": 2.5,
        "annual_income": 90000,
    }
    verified_docs = ["aadhaar"]

    html = generate_form_html(
        scheme_id="pm-kisan",
        profile=profile,
        schemes=schemes,
        lang="hi",
        verified_docs=verified_docs,
        session_id="sess-form-123",
    )

    # 1. Scheme name
    assert "पीएम-किसान" in html or "PM-KISAN" in html

    # 2. User's details prefilled
    assert "रमेश कुमार" in html
    assert "42" in html
    assert "उन्नाव" in html
    assert "2.5" in html

    # 3. Document checklist with tick status
    assert "आधार कार्ड" in html or "Aadhaar Card" in html
    assert "[✔]" in html  # verified doc
    assert "[ ]" in html  # unverified docs

    # 4. Official link
    assert "https://pmkisan.gov.in" in html

    # 5. Mandatory note
    assert "Draft prepared by Sahayak. Submit on the official portal." in html
    assert "सहायक (Sahayak) द्वारा तैयार किया गया प्रारूप" in html

    # 6. Print CSS for single A4 page
    assert "size: A4 portrait" in html
    assert "@media print" in html
    assert ".toolbar" in html

    # 7. Hindi text rendering font
    assert "Noto Sans Devanagari" in html


def test_form_agent_returns_structured_dict():
    """Verify form_agent returns reply with official link and printable form url."""
    schemes = load_schemes()
    profile = {"name": "Suresh", "occupation": "farmer", "land_acres": 1.5}

    res_hi = form_agent(
        scheme_id="pm-kisan",
        profile=profile,
        schemes=schemes,
        lang="hi",
        session_id="sess-agent-test",
    )

    assert res_hi["scheme_id"] == "pm-kisan"
    assert "https://pmkisan.gov.in" in res_hi["official_link"]
    assert "https://pmkisan.gov.in" in res_hi["reply"]
    assert "/form/pm-kisan?session_id=sess-agent-test" in res_hi["form_url"]
    assert "Draft prepared by Sahayak. Submit on the official portal." in res_hi["reply"]
    assert len(res_hi["html"]) > 1000

    # English version
    res_en = form_agent(
        scheme_id="pm-kisan",
        profile=profile,
        schemes=schemes,
        lang="en",
        session_id="sess-agent-test",
    )
    assert "Draft prepared by Sahayak. Submit on the official portal." in res_en["reply"]
    assert "https://pmkisan.gov.in" in res_en["reply"]


def test_get_form_endpoint_returns_printable_html():
    """Test GET /form/{scheme_id} endpoint returns status 200 with HTML."""
    # Setup session with profile data
    sess = get_or_create_session("sess-endpoint-test", lang="hi")
    sess["profile"] = {
        "name": "कमला देवी",
        "age": 38,
        "gender": "female",
        "state": "बिहार",
        "occupation": "homemaker",
    }
    sess["verified_docs"] = ["aadhaar", "ration_card"]

    response = client.get("/form/pm-jay?session_id=sess-endpoint-test&lang=hi")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    html = response.text
    assert "कमला देवी" in html
    assert "https://pmjay.gov.in" in html
    assert "Draft prepared by Sahayak. Submit on the official portal." in html
    assert "Noto Sans Devanagari" in html
    assert "@media print" in html
    assert "[✔]" in html


def test_get_form_query_endpoint():
    """Test GET /form fallback endpoint with query params."""
    response = client.get("/form?scheme_id=pm-kisan")
    assert response.status_code == 200
    assert "https://pmkisan.gov.in" in response.text
    assert "Draft prepared by Sahayak. Submit on the official portal." in response.text


def test_coordinator_handles_form_intent_transition():
    """Test coordinator transitions to FORM state when user requests form."""
    sess_id = "sess-coord-form"
    reset_session(sess_id, lang="hi")
    sess = get_or_create_session(sess_id, lang="hi")
    sess["state"] = "MATCH"
    sess["selected_scheme"] = "pm-kisan"
    sess["profile"] = {"name": "Ramesh", "occupation": "farmer", "land_acres": 2.0}

    # User expresses form intent
    res = handle_message(sess_id, "please give me the form for pm-kisan")

    assert res["state"] == "FORM"
    assert any(t["agent"] == "form" for t in res["trace"])
    assert "/form/pm-kisan" in res["reply"]
    assert "https://pmkisan.gov.in" in res["reply"]
    assert "Draft prepared by Sahayak. Submit on the official portal." in res["reply"]


def test_coordinator_handles_form_intent_hindi():
    """Test coordinator transitions to FORM state for Hindi form request."""
    sess_id = "sess-coord-form-hi"
    reset_session(sess_id, lang="hi")
    sess = get_or_create_session(sess_id, lang="hi")
    sess["state"] = "MATCH"
    sess["selected_scheme"] = "pm-kisan"
    sess["profile"] = {"name": "Ramesh", "occupation": "farmer", "land_acres": 2.0}

    res = handle_message(sess_id, "मुज्हे पीएम-किसान का फ़ॉर्म चाहिए")

    assert res["state"] == "FORM"
    assert any(t["agent"] == "form" for t in res["trace"])
    assert "/form/pm-kisan" in res["reply"]
    assert "https://pmkisan.gov.in" in res["reply"]
    assert "Draft prepared by Sahayak. Submit on the official portal." in res["reply"]


def test_upload_doc_updates_session_verified_docs_for_form():
    """Test that uploading a doc records it in session verified_docs,
    which then displays as verified [✔] on the form.
    """
    sess_id = "sess-doc-to-form"
    reset_session(sess_id, lang="hi")
    sess = get_or_create_session(sess_id, lang="hi")
    sess["profile"] = {"name": "Anil"}
    sess["selected_scheme"] = "pm-kisan"

    mock_verify_res = {
        "doc_type": "aadhaar",
        "matches_checklist": True,
        "matched_doc_id": "aadhaar",
        "readable": True,
        "masked_id": "XXXX-XXXX-9999",
        "notes": "Verified Aadhaar Card.",
    }

    dummy_image = b"dummy-image-bytes"
    with patch("main.verify_document_image", return_value=mock_verify_res):
        upload_resp = client.post(
            "/upload-doc",
            files={"file": ("my_aadhaar.jpg", dummy_image, "image/jpeg")},
            data={"session_id": sess_id, "scheme_id": "pm-kisan", "lang": "hi"},
        )

    assert upload_resp.status_code == 200
    assert "aadhaar" in sess["verified_docs"]

    # Now fetch the form and verify [✔] is rendered for Aadhaar
    form_resp = client.get(f"/form/pm-kisan?session_id={sess_id}")
    assert form_resp.status_code == 200
    assert "[✔]" in form_resp.text


def test_download_pdf_button_and_auto_print_script():
    """Verify generate_form_html includes Download PDF button and auto-print script."""
    schemes = load_schemes()
    html = generate_form_html(
        scheme_id="pm-kisan",
        schemes=schemes,
        lang="hi",
    )

    # 1. Download PDF button in toolbar
    assert "download-pdf-btn" in html
    assert "Download PDF" in html
    assert "window.print()" in html

    # 2. Auto-print trigger script
    assert "auto_print" in html
    assert "URLSearchParams" in html
    assert "window.print()" in html


def test_form_agent_includes_pdf_url_and_reply_link():
    """Verify form_agent returns pdf_url with auto_print=true and link in reply."""
    schemes = load_schemes()
    res = form_agent(
        scheme_id="pm-kisan",
        schemes=schemes,
        lang="hi",
        session_id="sess-pdf-test",
    )

    assert "pdf_url" in res
    assert "/form/pm-kisan?session_id=sess-pdf-test&auto_print=true" in res["pdf_url"]
    assert "Download PDF" in res["reply"]
    assert res["pdf_url"] in res["reply"]


def test_get_form_with_auto_print_param():
    """Verify GET /form/{scheme_id}?auto_print=true serves page with auto-print logic."""
    response = client.get("/form/pm-kisan?auto_print=true")
    assert response.status_code == 200
    html = response.text
    assert "auto_print" in html
    assert "download-pdf-btn" in html
    assert "Download PDF" in html


def test_static_index_contains_download_pdf_button_and_handler():
    """Verify static/index.html contains Download PDF button on scheme cards and JS handler."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        index_html = f.read()

    assert "btn_pdf_" in index_html
    assert "Download PDF" in index_html
    assert "downloadFormPdf" in index_html
    assert "auto_print=true" in index_html
    assert ".chat-pdf-btn" in index_html
