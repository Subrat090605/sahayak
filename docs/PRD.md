# Product Requirements — Sahayak

## Vision
Anyone should be able to *speak* their situation and learn which government schemes they can use, what papers they need, and what to do next.

## Target users
- Primary: low-literacy, Hindi-speaking citizens (small farmers, students, elderly) using a phone browser, often with help from a family member or CSC operator.
- Secondary: NGO workers and village-level helpers assisting many people.

## Scope (hackathon, 1 day)
**In scope**
- 4 schemes: PM-KISAN, Ayushman Bharat PM-JAY, PM Ujjwala Yojana, one national scholarship scheme (data verified by the builder from official portals).
- Languages: Hindi and English (mixed speech tolerated).
- Voice via browser Web Speech API with text fallback.
- Agents: Profile extractor, Eligibility, Document, Form, Follow-up, plus Coordinator.
- Outputs: eligibility results with reasons, document checklist, printable draft form (PDF via print), `.ics` reminders.

**Out of scope**
- Logging in to or automating government portals.
- Real Aadhaar/OTP flows, payments, storing user documents.
- More than 4 schemes or state-specific schemes (stretch only).

## Functional requirements
| ID | Requirement | Priority |
|---|---|---|
| F1 | User can speak or type in Hindi/English | Must |
| F2 | System extracts profile fields from free speech | Must |
| F3 | System asks one missing-field question at a time | Must |
| F4 | Eligibility computed by deterministic rules from `schemes.json` | Must |
| F5 | Each result shows status, plain-language reason, official link | Must |
| F6 | Reply is spoken aloud in the user's language | Must |
| F7 | Document checklist per matched scheme | Must |
| F8 | Uploaded document photo checked against checklist | Should |
| F9 | Printable pre-filled draft form | Must |
| F10 | `.ics` reminders (3/7/30 days) | Should |
| F11 | Live agent trace panel in UI | Must (judge impact) |
| F12 | Demo mode with sample profile | Must |
| F13 | Graceful failure handling | Must |

## Non-functional
- Typical response under ~5 s.
- Works in latest Chrome on desktop and Android.
- No document storage; PII masked in logs.

## Success criteria
- Hindi voice demo: farmer profile → matched schemes → checklist → PDF → reminders in under 2 minutes without a failure.
- 5 eligibility tests pass.
- Judges can see which agent did what.

## Risks and mitigations
| Risk | Mitigation |
|---|---|
| Wrong eligibility info | Rules in verified JSON; official links; disclaimer |
| Speech recognition fails | Text fallback + demo mode |
| LLM hallucination | Facts only from JSON; guardrail prompt; tests |
| Time overrun | Cut order in `docs/ROADMAP.md` |
