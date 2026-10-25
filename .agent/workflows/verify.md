---
description: Run data validation, tests and a health check
---
1. Run `python validate_data.py` and list any missing keys or remaining TODO values.
2. Run `pytest -q` and fix failures in code (never weaken a test to make it pass).
3. Start the server with `uvicorn main:app --reload`, call `/health`, and report the result.
4. Summarize in three lines: data status, test status, server status.
