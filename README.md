# Sahayak (सहायक) — Voice-First Citizen Scheme Discovery & Paperwork Platform

> **"बोलकर जानें अपनी सरकारी योजनाएं"** — Discover government welfare schemes by voice, understand required documents, generate pre-filled printable application drafts, and schedule calendar reminders without paperwork confusion.

Built for **Hacker House Goa 2026**. Voice prompt scripts and rapid development dictated with **Wispr Flow**.

---

## 📸 Screenshots & Showcase

| 1. Voice Chat & Live Multi-Agent Trace | 2. Scheme Cards & Deterministic Reasons |
| :---: | :---: |
| ![Voice Chat & Multi-Agent Execution Trace](docs/screenshots/01_chat_trace.png)<br>*(Voice input with live multi-agent execution traces)* | ![Scheme Cards & Eligibility Reasons](docs/screenshots/02_scheme_cards.png)<br>*(Deterministic rule evaluation with official portal links)* |

| 3. Document Checklist & Vision Verification | 4. Single-Page A4 Printable Application Draft |
| :---: | :---: |
| ![Document Checklist & Vision Upload Check](docs/screenshots/03_document_checklist.png)<br>*(Issuing authorities + in-memory vision AI ID masking)* | ![Printable A4 Application Draft](docs/screenshots/04_printable_form_a4.png)<br>*(One-page print CSS draft pre-filled with citizen details)* |

| 5. iCalendar (.ics) Automated Reminders | 6. One-Click Demo Mode (No Mic Needed) |
| :---: | :---: |
| ![iCalendar Reminders Schedule](docs/screenshots/05_calendar_reminders.png)<br>*(Automated 3d, 7d, 30d follow-up timeline import)* | ![Automated Demo Mode Showcase](docs/screenshots/06_demo_mode.png)<br>*(Plays Unnao farmer scenario automatically)* |

---

## 🎯 The Problem
Over **₹3 lakh crore** in direct welfare benefits remain under-claimed across rural and semi-urban India because:
1. Eligibility rules are complex, scattered, and often published in bureaucratic English.
2. Citizens do not know which documents are mandatory or where local offices issue them.
3. Form-filling errors and missed deadlines lead to rejected applications.

**Sahayak** solves this by letting any citizen simply speak in Hindi, English, or mixed Hinglish. A collaborative network of 5 specialized agents extracts details, deterministically evaluates verified government rules, prepares a single-page printable application draft, and sets submission reminders.

---

## 🤖 The Final 5 Specialized Agents

Sahayak uses a decoupled multi-agent architecture where agents communicate through an in-memory session coordinator:

```
Citizen Voice/Text
       │
       ▼
[ Coordinator ] ── State Machine: COLLECT_PROFILE → MATCH → DOCUMENTS → FORM → REMINDERS
       │
       ├─► 1. Profile Agent    ── Free-form speech/text extraction & normalization
       ├─► 2. Eligibility Agent── Pure-Python deterministic engine on verified data
       ├─► 3. Document Agent   ── Verified checklists & in-memory vision checking
       ├─► 4. Form Agent       ── Single-page A4 printable HTML draft with auto-print
       └─► 5. Follow-up Agent  ── RFC 5545 iCalendar schedule (3d, 7d, 30d)
```

1. **Profile Agent (`agents.profile_agent`)**:
   - Converts natural language speech/text into sanitized profile fields (`occupation`, `land_acres`, `annual_income`, `district`, `state`, `age`, `gender`).
   - Supports Hindi, English, and Hinglish with schema-validated JSON extraction and robust regex fallback.

2. **Eligibility Agent (`agents.eligibility_agent`)**:
   - Evaluates citizen profile against verified criteria in `data/schemes.json` using a **pure-Python deterministic rule engine** (`eligibility.py`).
   - **Zero LLM hallucinations**: LLMs are never allowed to invent or modify rules, amounts, or portals.
   - If information is missing, asks **exactly one focused question per turn** following a strict importance hierarchy. Once complete, explains eligible matches with benefits and official links.

3. **Document Agent (`agents.document_agent` & `agents.verify_document_image`)**:
   - Provides verified document requirements with exact issuing departments (e.g. Tehsil, CSC, UIDAI, Food Supplies).
   - Inspects uploaded document photos in-memory: identifies document type, checks checklist matching, evaluates text readability, and **masks ID numbers** (e.g. `XXXX-XXXX-1234`).
   - **Strict Privacy**: Uploaded photos are never saved to disk and are processed entirely in ephemeral RAM.

4. **Form Agent (`agents.form_agent` & `agents.generate_form_html`)**:
   - Generates a pre-filled, single-page A4 application draft (`/form/{scheme_id}`) incorporating verified document ticks [✔], citizen profile, official portal links, print CSS `@page { size: A4; margin: 12mm; }`, and Devanagari typography (`Noto Sans Devanagari`).
   - Features a one-click **"Download PDF"** trigger that automatically launches the browser print dialog.

5. **Follow-up Agent (`agents.followup_agent` & `agents.generate_ics`)**:
   - Generates an RFC 5545 `.ics` calendar file with standardized milestones:
     - **3 Days**: Collect required documents from local authorities.
     - **7 Days**: Submit completed application on the official government portal.
     - **30 Days**: Check application status and verification updates.
   - Preserves real official deadlines from `schemes.json` when present.

---

## ⚡ High-Resilience LLM Gateway (`llm.py`)

- **Primary Provider**: Google Gemini 2.5/2.0 Flash via the official `google-genai` SDK.
- **Secondary Provider**: Groq (Llama 3.3 70B & Llama 4 Scout Vision) via the `groq` SDK.
- **Auto-Failover**: Primary failure or HTTP 429 triggers an immediate 1-second backoff retry, then falls back seamlessly to the secondary provider.
- **Offline Capable**: The app works cleanly even with **zero API keys** using deterministic rule engines, structured template replies, and regex extractors.

---

## 🛠️ Complete Setup Instructions

### 1. Prerequisites
- **Python 3.11+**
- Modern Web Browser (Google Chrome, Edge, or Brave for Web Speech API support)
- Git

### 2. Clone Repository & Create Virtual Environment
```bash
# Clone the repository
git clone https://github.com/Subrat090605/Fd-watcher-.git
cd sahayak

# Create virtual environment
python -m venv .venv

# Activate virtual environment
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
Open `.env` and provide your API keys:
```env
# Primary LLM
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Fallback LLM & Vision
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct

# Configuration
LLM_PROVIDER=gemini
LLM_TIMEOUT=15.0
```
*(Note: If you do not have API keys, Sahayak will automatically fall back to rule-based evaluation and mock demo scenarios without crashing).*

### 5. Launch the Web Application
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
Open your browser at:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 🎬 Running in Demo Mode (No Microphone Needed)
For hackathons, video recording, or environments without microphone access:
1. Click the **`▶️ डेमो मोड (Demo Mode)`** button in the header.
2. Sahayak calls `POST /demo/load` to preload the sample Unnao farmer profile (2 acres land, low income) and automatically plays the multi-turn conversational journey step-by-step.
3. The live agent trace panel updates dynamically on every turn.

Alternatively, test from the command line:
```bash
# Automated 2-turn farmer scenario
python chat_cli.py --demo

# Interactive CLI REPL
python chat_cli.py
```

---

## 🧪 Testing & Quality Assurance

### Run Automated Unit & Integration Tests
```bash
pytest -q
```
*Current test suite: **74 passing tests** across eligibility rules, coordinator state machine, document verification, form printing, calendar reminders, reliability, and demo mode.*

### Manual Scenario Coverage (`docs/TESTING.md`)
1. **Hindi farmer from Unnao with 2 acres**: Verified full PM-KISAN flow with documents & reminders.
2. **Student with low family income (English)**: Verified National Scholarship matching.
3. **Incomplete info**: Verified agent asks exactly one question at a time.
4. **Mixed Hindi + English sentence**: Verified robust multilingual field extraction.
5. **High-income salaried profile**: Verified honest decline without hallucinated schemes.
6. **Mic blocked or unsupported**: Verified graceful fallback to text input.
7. **No API keys configured**: Verified resilient fallback without server crashes.

---

## 🛡️ Safety, Privacy & Ethical Guardrails

- **No Hallucinated Rules**: Eligibility is calculated using strict, deterministic boolean logic directly mapped from government Gazette notifications.
- **Zero Document Storage**: Uploaded identity documents are parsed entirely in volatile memory and never written to disk or database.
- **Privacy Masking**: Government identifiers (such as Aadhaar numbers) are masked to show only the last 4 digits (`XXXX-XXXX-1234`).
- **No Real Actions**: Sahayak prepares printable application drafts only. It never submits data to live government portals or initiates real banking transactions.
- **Official Portal Links**: Every single result includes the verified official portal link (e.g. `pmkisan.gov.in`, `pmjay.gov.in`) with mandatory verification guidance.

---

## ⚠️ Disclaimer
**Sahayak is an assistive prototype, not an official government service.** All eligibility results and application drafts are for guidance only. Always verify rules, deadlines, and criteria on the respective official government portals.

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
