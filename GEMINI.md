# Antigravity-specific notes (overrides AGENTS.md only where they conflict)

- Follow everything in AGENTS.md.
- Prefer the Editor view and one agent at a time for this project; use parallel agents only for independent files (for example UI vs tests).
- For multi-file work, produce a short plan first, then implement.
- Use the integrated terminal to run `uvicorn main:app --reload` and `pytest -q` yourself and fix errors before reporting.
- When testing the UI, use the integrated browser on http://127.0.0.1:8000 and report what you actually see.
- Never read, print, or paste the contents of `.env`.
