# Architecture

```mermaid
flowchart TD
  subgraph Client ["Client Layer (Browser)"]
    U["Citizen (Voice / Text / Upload)"] --> UI["Sahayak Web UI<br/>(Web Speech API + Live Agent Trace)"]
    UI -->|POST /chat| API_CHAT["/chat"]
    UI -->|POST /upload-doc| API_DOC["/upload-doc"]
    UI -->|GET /form/{id}| API_FORM["/form/{scheme_id}"]
    UI -->|GET /reminders.ics| API_REM["/reminders.ics"]
    UI -->|POST /demo/load| API_DEMO["/demo/load"]
  end

  subgraph Server ["FastAPI Application (main.py)"]
    API_CHAT --> COORD["Coordinator (coordinator.py)<br/>In-memory Session State Machine"]
    API_DOC --> AG_DOC
    API_FORM --> AG_FORM["Form Agent<br/>(A4 Printable HTML Draft)"]
    API_REM --> AG_REM["Follow-up Agent<br/>(RFC 5545 .ics Calendar)"]
    API_DEMO --> COORD

    subgraph Agents ["Multi-Agent System (agents.py)"]
      COORD -->|1. Extract profile| AG_PROF["Profile Agent<br/>(Field Extraction & Sanitization)"]
      COORD -->|2. Check missing & evaluate| AG_ELIG["Eligibility Agent<br/>(Follow-up or Match Explanation)"]
      COORD -->|3. Query checklist| AG_DOC["Document Agent<br/>(Checklist & Vision Verification)"]
      COORD -->|4. Generate draft| AG_FORM
      COORD -->|5. Schedule reminders| AG_REM
    end

    subgraph Deterministic ["Deterministic Rule Engine"]
      AG_ELIG --> ENGINE["eligibility.py<br/>(Pure-Python Rule Evaluator)"]
      ENGINE --> DB[("data/schemes.json<br/>(Verified Government Criteria)")]
      AG_DOC --> DB
      AG_FORM --> DB
      AG_REM --> DB
    end

    subgraph LLM_Layer ["LLM Resilience Gateway (llm.py)"]
      AG_PROF -.-> LLM["_execute_with_fallback<br/>(Retries + Auto-fallback)"]
      AG_ELIG -.-> LLM
      AG_DOC -.-> LLM
      LLM --> GEMINI["Primary: Google Gemini<br/>(Gemini 2.5/2.0 Flash)"]
      LLM -->|Fallback on 429/Error| GROQ["Secondary: Groq<br/>(Llama 3.3 70B & Scout Vision)"]
    end
  end
```

## The 5 Specialized Agents
| Agent | Implementation | Responsibility & Guardrails |
|---|---|---|
| **Profile Agent** | `agents.py` (`profile_agent`) | Extracts citizen attributes (occupation, land acres, income, district, age, gender) from Hindi, English, or mixed speech/text. Uses schema-validated JSON extraction with robust regex/rule-based fallbacks. |
| **Eligibility Agent** | `agents.py` (`eligibility_agent`) | Enforces deterministic evaluation against `data/schemes.json` via `eligibility.py` (zero LLM hallucinations). If fields are missing, asks **exactly one focused question** per turn. Otherwise, explains eligible matches with official benefits and links. |
| **Document Agent** | `agents.py` (`document_agent`, `verify_document_image`) | Generates verified required document checklists with issuing authorities. Inspects uploaded document images (`/upload-doc`) in-memory, checks checklist alignment, evaluates readability, masks ID numbers (`XXXX-XXXX-1234`), and stores **zero** images to disk. |
| **Form Agent** | `agents.py` (`form_agent`, `generate_form_html`) | Pre-fills a clean, single-page A4 application draft (`/form/{scheme_id}`) incorporating verified document ticks [✔], citizen profile, official portal links, print CSS `@page { size: A4; margin: 12mm; }`, and Devanagari typography (`Noto Sans Devanagari`). |
| **Follow-up Agent** | `agents.py` (`followup_agent`, `generate_ics`) | Generates RFC 5545 iCalendar files (`/reminders.ics`) with reminders at **3 days** (document collection), **7 days** (submission), and **30 days** (status check). Only includes official deadlines when present in verified scheme data. |

## Coordinator & Session State Machine
The `Coordinator` in `coordinator.py` manages multi-turn dialogs and state transitions:
`COLLECT_PROFILE → MATCH → DOCUMENTS → FORM → REMINDERS → DONE`

- **COLLECT_PROFILE**: Loops turn-by-turn until all required criteria are gathered, asking one question at a time following global `FIELD_PRIORITY`.
- **MATCH**: Displays eligible and potential schemes with benefits, reasons met, and direct links to official government portals.
- **DOCUMENTS**: Renders the complete document checklist with local issuing authorities and activates document verification.
- **FORM / REMINDERS**: Prepares printable drafts and downloadable calendar schedules.
- **Start Over**: The user can reset at any turn by speaking or typing "start over", "शुरू से", "reset", or clicking the reset button.

## Session Object Schema (In-Memory)
```json
{
  "session_id": "uuid-v4-string",
  "lang": "hi",
  "state": "COLLECT_PROFILE",
  "profile": {
    "name": "रामेश कुमार (Ramesh Kumar)",
    "occupation": "farmer",
    "state": "Uttar Pradesh",
    "district": "Unnao",
    "land_acres": 2.0,
    "annual_income": 80000
  },
  "missing": ["annual_income"],
  "matches": [],
  "selected_scheme": "pm-kisan",
  "verified_docs": ["aadhaar"],
  "history": []
}
```
*Note: Sessions are maintained purely in-memory (`dict[str, dict]`) without persistent database storage, ensuring zero data retention.*

## Endpoints
| Method | Path | Request | Response | Description |
|---|---|---|---|---|
| `GET` | `/health` | None | `{"status": "ok"}` | Service liveness health check. |
| `POST` | `/chat` | `{session_id, message, lang}` | `{reply, lang, state, matches, trace}` | Multi-agent conversational endpoint with live execution traces and state management. |
| `POST` | `/upload-doc` | `multipart/form-data` (file, session_id, scheme_id, lang) | `{doc_type, matches_checklist, matched_doc_id, readable, masked_id, notes}` | In-memory vision document verification with ID masking. |
| `GET` | `/form/{scheme_id}` | Query: `session_id`, `lang`, `auto_print` | `text/html` (Printable A4) | Single-page printable application draft with auto-print trigger. |
| `GET` | `/reminders.ics` | Query: `scheme_id`, `session_id`, `lang` | `text/calendar` (RFC 5545) | Calendar reminder schedule (3-day, 7-day, 30-day). |
| `POST` | `/demo/load` | `{session_id, lang, profile}` | `{status, session_id, profile, state, matches, reply, trace, demo_steps}` | Preloads sample Unnao farmer profile and returns scripted playback turns. |

## Live Trace Format
Each turn returns a transparent log of agent actions displayed in the UI side panel:
```json
[
  {"agent": "profile", "action": "extracted 2 field(s): occupation, land_acres", "ms": 48},
  {"agent": "eligibility", "action": "asking for missing field: annual_income", "ms": 112}
]
```

## Failure Handling & Reliability Architecture
1. **Model Errors**: Automatic retry (attempt 1 + 1 retry with 1s backoff) on primary provider, followed by automated fallback to secondary provider (Gemini ↔ Groq). Unhandled exceptions return localized guidance preserving state.
2. **Timeouts**: Client-side `AbortController` (25s) and backend timeouts (`TimeoutError`, `asyncio.TimeoutError`) return clean timeout notices with retry buttons.
3. **Empty Speech**: Caught on Web Speech `onerror` (`no-speech`) and empty `recognition.onend`, rendering assistive guidance and auto-focusing text input.
4. **Unsupported Browser**: When Web Speech API is absent, UI provides graceful notification, disables mic button with tooltip, and highlights the text box.
5. **Unclear Language**: `is_unclear_message()` catches gibberish and symbol-only inputs (`???`, `!@#$%`), requesting simple clarification without corrupting state.
6. **Retry Button**: Standardized `🔄 पुनः प्रयास करें (Retry)` component across all error surfaces.
