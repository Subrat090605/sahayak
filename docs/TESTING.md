# Testing and demo plan

## Automated tests (`pytest`)
| # | Profile | Expectation |
|---|---|---|
| 1 | Farmer, UP, 2 acres, low income | PM-KISAN eligible or maybe, with reasons |
| 2 | Student, low family income | Scholarship eligible or maybe |
| 3 | BPL woman without LPG connection | Ujjwala eligible or maybe |
| 4 | Elderly, low income, no insurance | Ayushman result with reasons |
| 5 | High-income salaried | No scheme marked eligible |

Also test: missing fields are reported, `TODO` values give "maybe", unknown fields do not crash.

## Manual scenarios (run before recording)
1. Hindi farmer from Unnao with 2 acres.
2. Student with low family income (English).
3. Incomplete info → agent asks one question at a time.
4. Mixed Hindi + English sentence.
5. User matches nothing → honest message, no invented schemes.
6. Mic blocked or unsupported → text fallback works.
7. API key removed → friendly error, no crash.

## Demo checklist
- [ ] Use **fake** data and fake documents only
- [ ] Headphones/quiet room; Chrome; mic permission granted
- [ ] Demo mode button works as a backup
- [ ] Browser zoom at ~110% so text is readable in the video

## 2-minute video script
| Time | Content |
|---|---|
| 0:00–0:15 | Problem: people miss schemes because the process is confusing and in the wrong language |
| 0:15–1:15 | Live Hindi voice demo: follow-up question → matched schemes → agent trace panel |
| 1:15–1:40 | Document checklist + document upload check |
| 1:40–1:55 | PDF download + reminders file |
| 1:55–2:00 | Impact line + "built by voice with Wispr Flow" |

## Recording tips
- Record screen + mic with OBS or the built-in recorder; do two takes.
- Keep the agent trace panel visible; it shows the multi-agent work to judges.
- Never show real Aadhaar, phone numbers, or API keys.
