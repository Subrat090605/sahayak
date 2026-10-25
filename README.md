# Sahayak (सहायक) — Voice Agent for Government Schemes & Paperwork

> Speak in Hindi or English. Sahayak finds the government schemes you may qualify for, tells you exactly which documents you need, pre-fills a draft application, and sets reminders.

Built for **Hacker House Goa 2026**. Prompts for the build were dictated by voice with **Wispr Flow**.

## The problem
Millions of people miss welfare schemes they qualify for because eligibility information is scattered, confusing, and mostly in English.

## What it does
1. **Voice in, voice out** — Hindi / English (browser speech APIs).
2. **Eligibility agent** — asks one follow-up question at a time, then matches schemes using *code-enforced rules* from `data/schemes.json` (the LLM never invents rules).
3. **Document agent** — lists required papers in simple language; checks an uploaded photo against the checklist (ID numbers masked, nothing stored).
4. **Form agent** — generates a printable, pre-filled draft (download as PDF).
5. **Follow-up agent** — creates a calendar (.ics) file with reminders.

## Architecture (short)
Browser (mic + chat + agent trace panel) → FastAPI `/chat` → Coordinator → {Profile, Eligibility, Document, Form, Follow-up} agents → `schemes.json` + deterministic eligibility engine. See `docs/ARCHITECTURE.md`.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # add GEMINI_API_KEY and/or GROQ_API_KEY
uvicorn main:app --reload
# open http://127.0.0.1:8000 in Chrome
```

## Tests
```bash
pytest -q
```

## Project docs
| File | Purpose |
|---|---|
| `AGENTS.md` / `GEMINI.md` | Rules for Antigravity (also read by Cursor, Claude Code, Codex) |
| `docs/ANTIGRAVITY_SETUP.md` | Antigravity + Gemini/Groq setup |
| `docs/PRD.md` | Scope, users, requirements |
| `docs/ARCHITECTURE.md` | Components, API, state machine |
| `docs/DATA_SCHEMA.md` | `schemes.json` and profile schema |
| `docs/PROMPTS.md` | Voice prompt script (Wispr Flow), start to finish |
| `docs/ROADMAP.md` | Hour-by-hour checklist |
| `docs/TESTING.md` | Test cases + demo video script |
| `docs/SAFETY_AND_LIMITATIONS.md` | Guardrails and honest limits |
| `docs/SUBMISSION.md` | Pitch and submission text |

## Disclaimer
Sahayak is an assistive prototype, **not** an official government service. Eligibility results are guidance only. Always verify on the official portal linked in each result.

## License
MIT
