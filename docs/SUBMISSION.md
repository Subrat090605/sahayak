# Submission text (edit before submitting)

## Title
Sahayak — a voice-first multi-agent assistant for government schemes

## One-liner
Speak your situation in Hindi or English; Sahayak finds the schemes you may qualify for, lists the exact documents, drafts the form, and sets reminders.

## Problem
Millions of Indians miss welfare benefits because information is scattered, written in complex language, and mostly in English. Forms and document requirements are confusing, so eligible people never apply.

## Solution
Sahayak is a team of cooperating AI agents behind a simple voice interface:
- **Profile agent** turns free speech into structured details.
- **Eligibility agent** asks one question at a time and matches schemes using code-enforced rules from verified data, so the AI cannot invent eligibility.
- **Document agent** lists required papers in simple language and checks an uploaded photo.
- **Form agent** prepares a printable pre-filled draft.
- **Follow-up agent** creates calendar reminders.

## What makes it different
- Rules live in verified data and code, not in model memory.
- Every answer links to the official source.
- Privacy by design: no document storage, masked IDs.
- Built end-to-end by voice using Wispr Flow.

## Tech stack
Python, FastAPI, Gemini and Groq APIs (multi-agent pipeline, JSON-mode extraction, vision), Antigravity IDE, Web Speech API, vanilla JS, pytest.

## Impact
Helps first-time applicants, village helpers, and NGOs prepare correctly in their own language, reducing rejected or abandoned applications.

## What's next
More schemes and states, more languages, WhatsApp interface, verifiable application receipts.

## Links
- Repo: TODO
- Demo video: TODO
- Live demo (optional): TODO
