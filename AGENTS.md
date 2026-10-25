# Project rules for AI coding agents (Antigravity, Cursor, Claude Code, Codex)

You are helping build **Sahayak**, a voice-first multi-agent web app that helps Indian citizens discover government schemes, prepare documents, draft forms, and set reminders. Read `docs/PRD.md`, `docs/ARCHITECTURE.md`, and `docs/DATA_SCHEMA.md` before making changes.

## Stack
- Backend: Python 3.11+, FastAPI, pydantic, pytest
- LLM providers (selected by `LLM_PROVIDER`): **Gemini** via the `google-genai` SDK, **Groq** via the `groq` SDK. Use the new `google-genai` package, never the deprecated `google-generativeai`.
- Frontend: single `static/index.html` (vanilla JS), Web Speech API (`hi-IN`, `en-IN`)
- Data: `data/schemes.json` (source of truth for all scheme facts)
- Keys and model names come only from environment variables. Never hard-code or print secrets.

## Hard rules
1. **Eligibility is decided by code** in `eligibility.py`, never by the LLM. The LLM only extracts profile fields and explains results.
2. The LLM may only state facts present in `schemes.json`. Never invent amounts, dates, rules, or links. If unknown, say so and point to the official link.
3. Every scheme answer includes the official link and a "verify on the official portal" line.
4. Never store uploaded documents. Mask ID numbers except the last 4 digits. Demos use fake data only.
5. Ask **one** follow-up question at a time. Keep replies short, in the user's language.
6. Every failure path (API error, rate limit, speech unsupported, unclear language) degrades to a friendly message and text input.
7. `llm.py` must support provider fallback: if the primary provider fails with a rate limit or server error and the other key exists, retry on the other provider.
8. Keep the code simple: small functions, type hints, no extra frameworks.

## Workflow
- After each change: run the app or tests, fix errors, then summarize in 2 lines.
- Update tests when changing `eligibility.py`.
- Commit after each completed step.
- Plan first for multi-file tasks; show the plan briefly, then execute.

## Do not
- Add databases, auth, or Docker unless asked.
- Scrape or automate government portals.
- Add features outside `docs/PRD.md` scope.
- Send real personal data to any model API.
