# 🇮🇳 सहायक (Sahayak) — Voice-First Multi-Agent Citizen Scheme Discovery

> **A voice-first, multi-agent AI assistant that helps Indian citizens discover, verify, document, draft, and track government welfare schemes in their own language.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Gemini & Groq](https://img.shields.io/badge/AI-Gemini%20%2B%20Groq%20Whisper-orange.svg)](https://aistudio.google.com/)
[![Tests](https://img.shields.io/badge/tests-80%20passed-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📌 Executive Summary

Millions of eligible Indian citizens miss out on critical government welfare benefits (PM-KISAN, Ayushman Bharat PM-JAY, PM Ujjwala Yojana, National Scholarships) due to scattered portals, bureaucratic jargon, English-only interfaces, and intimidating paperwork.

**Sahayak** solves this by placing a coordinated team of **5 specialized AI agents** behind an accessible voice interface:
1. Speak or type naturally in **Hindi**, **English**, or **Hinglish**.
2. Sahayak extracts your situation and matches you against **verified government gazette criteria** using a **pure-Python deterministic rule engine** (eliminating hallucinations).
3. If information is missing, it asks **exactly one focused question at a time**.
4. It prepares a localized **document checklist**, lets you snap photo proofs for **in-memory privacy-safe vision checks**, generates a **single-page A4 printable application draft**, and builds an **RFC 5545 calendar reminder schedule**.

---

## 🌟 Comprehensive Feature Catalog

### 1. 🎙️ Dual-Engine Voice & Audio System
- **Browser Native Speech Recognition (Default)**:
  - Zero-latency client-side speech-to-text via the Web Speech API (`webkitSpeechRecognition`).
  - Real-time interim transcript preview banner with Devanagari live rendering.
- **Server-Side Groq Whisper Speech-to-Text (`POST /transcribe`)**:
  - Dedicated **"Use server speech recognition"** toggle in the UI.
  - Streams audio captured through browser `MediaRecorder` directly to Groq's `whisper-large-v3-turbo` model (`GROQ_STT_MODEL`).
  - Delivers superior phonetic accuracy for regional Hindi dialects and accents, and functions seamlessly on browsers lacking native Web Speech API support.
- **Multilingual Voice Synthesis (TTS)**:
  - Dynamic speech synthesis reading out agent responses in natural Hindi or English.
  - Interactive **Mute / Unmute** header toggle with immediate audio interruption when the citizen starts speaking.
- **Robust Error Handling**:
  - Graceful fallbacks for empty speech (`no-speech`), denied mic permissions, and unsupported browsers with automatic focus redirection to the text input box.
  - Standardized **"🔄 पुनः प्रयास करें (Retry)"** button on all error surfaces.

---

### 2. 🤖 The 5 Specialized Autonomous Agents

```text
               ┌────────────────────────────────────────────────────────┐
               │         Citizen Voice / Speech / Text Input            │
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │          Multi-Agent Coordinator (coordinator.py)       │
               │   State Machine: COLLECT ──► MATCH ──► DOCS ──► FORM   │
               └───────────────────────────┬────────────────────────────┘
                                           │
       ┌───────────────────┬───────────────┼───────────────┬───────────────────┐
       ▼                   ▼               ▼               ▼                   ▼
┌──────────────┐    ┌──────────────┐┌──────────────┐┌──────────────┐    ┌──────────────┐
│Profile Agent │    │ Eligibility  ││Document Agent││  Form Agent  │    │Follow-up Agt │
│Field extract │    │ Pure-Python  ││Checklists &  ││A4 Single-Page│    │RFC 5545 .ics │
│& sanitization│    │deterministic ││Vision checks ││Printable Form│    │Milestone sync│
└──────────────┘    └──────────────┘└──────────────┘└──────────────┘    └──────────────┘
```

| Agent | Implementation | Key Capabilities & Safety Guardrails |
|---|---|---|
| **1. Profile Agent** | `agents.profile_agent` | Parses free-form spoken or written Hindi/English into sanitized JSON profile fields (`occupation`, `land_acres`, `annual_income`, `district`, `state`, `age`, `gender`, `caste_category`, `student_status`, `bpl_household`). Combines schema-constrained LLM parsing with regex/rule fallbacks. |
| **2. Eligibility Agent** | `agents.eligibility_agent` | **Zero Hallucinations Guarantee**: Evaluates citizen attributes against verified rules in `data/schemes.json` using pure Python code (`eligibility.py`). If fields are missing, asks **exactly one focused question per turn** following a strict priority hierarchy (income ➔ land ➔ location). Once satisfied, clearly explains eligible benefits with official links. |
| **3. Document Agent** | `agents.document_agent` & `agents.verify_document_image` | Produces verified document checklists with issuing authorities (Tehsil, CSC, Food Department, etc.). Handles camera image uploads (`POST /upload-doc`), checks document type and checklist alignment, inspects readability, and **masks identity numbers** (`XXXX-XXXX-1234`). |
| **4. Form Agent** | `agents.form_agent` & `agents.generate_form_html` | Generates a single-page printable application draft (`GET /form/{scheme_id}`) with verified document tick-marks `[✔]`, official portal links, `@page { size: A4; margin: 12mm; }` print CSS, and Devanagari typography (`Noto Sans Devanagari`). Features a one-click **"Download PDF"** trigger. |
| **5. Follow-up Agent** | `agents.followup_agent` & `agents.generate_ics` | Generates an RFC 5545 standard `.ics` calendar file (`GET /reminders.ics`) with reminders at **3 days** (gather documents), **7 days** (portal submission), and **30 days** (status check). Preserves real scheme deadlines and never invents fake dates. |

---

### 3. ⚡ High-Resilience LLM Gateway (`llm.py`)
- **Dual-Provider Architecture**:
  - **Primary**: Google Gemini 2.5/2.0 Flash via the official `google-genai` SDK.
  - **Secondary**: Groq (Llama 3.3 70B versatile & Llama 4 Scout Vision) via the `groq` SDK.
- **Auto-Failover with Exponential Backoff**:
  - Transparent 1-second backoff retry on HTTP 429 rate limits or network glitches.
  - Seamless fallback to the secondary provider if primary retries fail.
- **100% Offline Capable**:
  - The application works completely without API keys! Deterministic rule evaluation, structured template replies, and regex extractors ensure zero server crashes when offline.

---

### 4. 🔒 Privacy by Design & Safety Guardrails
- **Zero Document Storage**: Uploaded identity photos are processed strictly in volatile RAM and **never written to disk or database**.
- **PII Masking**: Government identifiers (such as Aadhaar numbers) are automatically masked to show only the last 4 digits (`XXXX-XXXX-1234`).
- **No Real Actions**: Sahayak prepares printable drafts only. It never submits data to live portals or initiates financial transactions.
- **Transparent Official Links**: Every single result includes a direct, verified government portal link (`pmkisan.gov.in`, `pmjay.gov.in`, `pmuy.gov.in`, `scholarships.gov.in`).
- **Smart Domain Inferences**: Citizens with annual income > ₹2.5L are inferred as non-BPL, preventing irrelevant questions (e.g. asking a high-income tech worker for gender on PM-Ujjwala).

---

### 5. ⚡ Live "Agents at Work" Execution Trace
- Interactive side panel dynamically displays real-time agent activities.
- Transparently shows the active agent, action taken, and execution latency in milliseconds (`ms`).
- Expandable / collapsible on desktop and mobile devices.

---

### 6. 🎬 1-Click Demo Mode (No Audio/Mic Required)
- **Header Button `▶️ डेमो मोड (Demo Mode)`**: Instantly preloads a representative farmer profile from Unnao, UP (2 acres land, ₹80,000 annual income) via `POST /demo/load`.
- **Automated Dialogue Playback**: Runs the full multi-turn conversational journey step-by-step, updating the agent trace panel and card outputs dynamically.
- **Command-Line Interface**:
  - `python chat_cli.py --demo`: Automated 2-turn farmer scenario.
  - `python chat_cli.py`: Interactive terminal conversation REPL.

---

### 7. 🎨 Rich UI Aesthetics & Modern Frontend
- Dark-theme glassmorphism with subtle ambient gradients and Indian tricolor accents (saffron `#f59e0b` and emerald `#10b981`).
- Responsive cards with verified benefit tags, issuing authority chips, and document tick status indicators.
- One-click shortcuts for demo scenarios, language toggle (Hindi / English), and audio mute.
- Prominent statutory disclaimers in header, footer, and draft forms.

---

## 📸 Screenshots & UI Walkthrough

| Screen | Description | Placeholder / Asset |
|---|---|---|
| **Chat & Live Agent Trace** | Real-time multilingual voice conversation with live agent execution trace panel. | [![Chat UI](docs/screenshots/chat_trace_placeholder.png)](docs/screenshots/) |
| **Scheme Eligibility Cards** | Matched government schemes showing benefits, reasons, and official portal links. | [![Scheme Cards](docs/screenshots/scheme_cards_placeholder.png)](docs/screenshots/) |
| **Document Checklist & Vision** | Verified document checklist with issuing authorities and in-memory photo verification. | [![Documents](docs/screenshots/document_checklist_placeholder.png)](docs/screenshots/) |
| **Printable A4 Form Draft** | Pre-filled single-page application draft with auto-print PDF trigger. | [![A4 Form](docs/screenshots/a4_form_draft_placeholder.png)](docs/screenshots/) |
| **Calendar Reminders (.ics)** | RFC 5545 reminder schedule for 3-day, 7-day, and 30-day submission tracking. | [![Reminders](docs/screenshots/reminders_ics_placeholder.png)](docs/screenshots/) |
| **1-Click Demo Mode** | Instant scripted playback of standard farmer scenario without needing a microphone. | [![Demo Mode](docs/screenshots/demo_mode_placeholder.png)](docs/screenshots/) |

---

## 🛠️ Complete Setup Instructions

### 1. Prerequisites
- **Python 3.11+**
- Modern Web Browser (Google Chrome, Microsoft Edge, or Brave for native speech support)
- Git

### 2. Clone Repository & Setup Virtual Environment
```bash
# Clone the repository
git clone https://github.com/Subrat090605/sahayak.git
cd sahayak

# Create Python virtual environment
python -m venv .venv

# Activate virtual environment:
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Windows (cmd):
.\.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
# Windows:
copy .env.example .env
# Linux / macOS:
cp .env.example .env
```

Open `.env` and configure your API keys:
```env
# Primary LLM Provider (Google Gemini)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Fallback LLM, Vision & Speech-to-Text (Groq)
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
GROQ_STT_MODEL=whisper-large-v3-turbo

# Configuration
LLM_PROVIDER=gemini
LLM_TIMEOUT=15.0
APP_ENV=dev
```
*(Note: If no API keys are provided, Sahayak automatically falls back to deterministic rule evaluations and regex extractors without crashing).*

### 5. Launch the Web Application
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
Open your browser at:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 📡 API Reference & Endpoints

| Method | Endpoint | Request Payload / Params | Response | Description |
|---|---|---|---|---|
| `GET` | `/health` | None | `{"status": "ok"}` | Service liveness health check. |
| `POST` | `/chat` | `{session_id, message, lang}` | `{reply, lang, state, matches, trace}` | Main multi-agent conversational endpoint. |
| `POST` | `/transcribe` | Multipart: `file` (audio), `lang` | `{"text": str, "status": "ok", "error": null}` | Groq Whisper speech-to-text audio transcription. |
| `POST` | `/upload-doc` | Multipart: `file` (image), `session_id`, `scheme_id`, `lang` | `{doc_type, matches_checklist, matched_doc_id, readable, masked_id, notes}` | In-memory vision document verification with ID masking. |
| `GET` | `/form/{scheme_id}` | Query: `session_id`, `lang`, `auto_print` | `text/html` (Single A4 Page) | Pre-filled printable HTML application draft. |
| `GET` | `/reminders.ics` | Query: `scheme_id`, `session_id`, `lang` | `text/calendar` (RFC 5545) | Calendar reminder file (3-day, 7-day, 30-day). |
| `POST` | `/demo/load` | `{session_id, lang, profile}` | `{status, session_id, profile, state, matches, reply, trace, demo_steps}` | Preloads sample Unnao farmer profile for 1-click demo playback. |
| `GET` | `/docs` | None | OpenAPI Swagger UI | Interactive API documentation. |
| `GET` | `/redoc` | None | ReDoc UI | Alternative API documentation view. |

---

## 🧪 Testing & Quality Assurance

### Run Automated Unit & Integration Tests
```bash
pytest -q
```
*Current test suite: **80 passed tests** across eligibility rules, coordinator state machine, document verification, form printing, calendar reminders, reliability, Groq Whisper STT, and demo mode.*

### Manual Scenario Coverage (`docs/TESTING.md`)
1. **Hindi farmer from Unnao with 2 acres**: Full PM-KISAN qualification flow with documents, printable draft, and calendar reminders.
2. **Student with low family income (English)**: National Scholarship Portal post-matric matching.
3. **Incomplete information**: System asks exactly one question per turn following field importance hierarchy.
4. **Mixed Hindi + English sentence (Hinglish)**: Multilingual field extraction and normalization.
5. **High-income salaried profile**: Deterministic decline without hallucinating ineligible benefits.
6. **Mic blocked or unsupported**: UI shows helpful guidance and falls back smoothly to text input.
7. **No API keys configured**: Resilient offline fallback using template replies and deterministic rules.

---

## 📂 Project Architecture & Directory Structure

```text
sahayak/
├── main.py                     # FastAPI routes, endpoints, static serving
├── coordinator.py              # Multi-agent coordinator & session state machine
├── agents.py                   # The 5 specialized agents (Profile, Eligibility, Document, Form, Follow-up)
├── eligibility.py              # Pure-Python deterministic rule engine (Zero Hallucination)
├── llm.py                      # Multi-provider gateway (Gemini + Groq Llama/Whisper fallback)
├── chat_cli.py                 # Command-line REPL and automated demo runner
├── requirements.txt            # Python dependencies
├── .env.example                # Example environment variable template
├── data/
│   └── schemes.json            # Verified scheme rules, benefits, issuing authorities, official links
├── static/
│   ├── index.html              # Single-page web application (UI, Web Speech, MediaRecorder, Trace)
│   └── favicon.ico
├── tests/
│   ├── test_eligibility.py     # Deterministic rule engine tests
│   ├── test_coordinator.py     # Multi-turn state machine tests
│   ├── test_agents.py          # Agent logic tests
│   ├── test_documents.py       # In-memory document verification tests
│   ├── test_form_reminders.py  # A4 printable form and RFC 5545 .ics tests
│   ├── test_reliability.py     # Failures, timeouts, and fallback tests
│   ├── test_demo.py            # 1-Click demo mode tests
│   └── test_transcribe.py      # Groq Whisper audio transcription tests
└── docs/
    ├── ARCHITECTURE.md         # Component diagrams and data flow
    ├── DATA_SCHEMA.md          # JSON schema for schemes and profiles
    ├── TESTING.md              # 7 manual test scenarios & demo script
    ├── SAFETY_AND_LIMITATIONS.md # Guardrails, PII masking, privacy policies
    ├── SUBMISSION.md           # Hackathon pitch text and links
    └── screenshots/            # UI screenshot assets
```

---

## ⚠️ Disclaimer
**Sahayak is an assistive prototype, not an official government service.** All eligibility evaluations and application drafts are for guidance only. Always verify rules, deadlines, and criteria on the respective official government portals.

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
