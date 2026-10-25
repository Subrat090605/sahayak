# Roadmap — one-day build (check boxes as you go)

Deadline: **Oct 26, 11:59 PM**. Start as early as possible; Oct 26 morning is your buffer.

## Phase 0 — Setup (0:00–1:00)
- [ ] Python 3.11+, Antigravity, Chrome installed
- [ ] Gemini and/or Groq API key in `.env` (see `docs/ANTIGRAVITY_SETUP.md`)
- [ ] Repo created, files from this pack copied in, first commit
- [ ] Wispr Flow tested inside the Antigravity agent panel

## Phase 1 — Verified data (1:00–2:30)
- [ ] `data/schemes.json` created from template for 4 schemes
- [ ] **Every rule/document/link verified on official portals by you**
- [ ] `last_verified` and `source_note` filled

## Phase 2 — Eligibility engine (2:30–3:30)
- [ ] `eligibility.py` with operators from `DATA_SCHEMA.md`
- [ ] 5 profile tests pass

## Phase 3 — Agents + coordinator (3:30–6:00)
- [ ] `llm.py` wrapper
- [ ] Profile agent (extract fields, Hindi + English)
- [ ] Eligibility agent (one question at a time, explain results)
- [ ] Coordinator + `/chat` + session state + trace
- [ ] Terminal chat script works

## Phase 4 — Voice UI (6:00–7:30)
- [ ] `static/index.html` with mic, chat, language toggle, trace panel
- [ ] Speech recognition + spoken replies (hi-IN / en-IN)
- [ ] Text fallback

## Phase 5 — Document agent (7:30–8:30)
- [ ] Checklist per scheme
- [ ] Upload + vision check (masked IDs, nothing stored)

## Phase 6 — Form + reminders (8:30–10:00)
- [ ] Printable draft form + Download PDF button
- [ ] `.ics` reminders

## Phase 7 — Reliability (10:00–11:00)
- [ ] Failure handling, loading states
- [ ] Demo mode button
- [ ] README final, architecture diagram renders

## Phase 8 — Test and record (11:00–13:00)
- [ ] 5 test cases from `TESTING.md`
- [ ] Video recorded (plus a backup take)
- [ ] Pitch and submission text finalized (`SUBMISSION.md`)
- [ ] Submit with at least 2 hours of buffer

## If you fall behind, cut in this order
1. Document upload check (keep the checklist)
2. Reminders `.ics`
3. Mixed-language handling
4. **Never cut:** eligibility engine, voice flow, form, demo mode

## Stretch (only after everything above works)
- Sarvam AI voice for better Hindi
- One more scheme or state-specific scheme
- Deploy to Render/Railway
- Small on-chain receipt (if the hackathon needs a crypto element)
