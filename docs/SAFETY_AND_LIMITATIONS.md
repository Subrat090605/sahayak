# Safety and limitations

## Guardrails built in
- **Rules in code, not in the model:** eligibility comes from `eligibility.py` + `schemes.json`.
- **Facts only from data:** the LLM may not invent amounts, dates, rules, or links.
- **Official link on every answer** plus a "verify on the official portal" line.
- **Privacy:** uploads are processed in memory, never saved; ID numbers masked except the last 4 digits; PII not written to logs.
- **Honest uncertainty:** unknown or `TODO` rules → "maybe", with the missing information stated.
- **No portal automation:** Sahayak prepares drafts; users submit on official portals themselves.

## Data handling with third-party model APIs
- Free-tier model APIs may use prompts to improve their models. All demos and tests use **fake data only**.
- Only the minimum profile fields needed are sent to the model; document images are sent for a one-off check and never stored.

## Known limitations
- Covers only 4 schemes in this prototype.
- Rules reflect the data verified on the `last_verified` date; schemes change over time.
- Browser speech recognition quality varies by device, accent, and noise.
- Eligibility is guidance, not a legal or official determination.
- In-memory sessions are lost when the server restarts.

## Responsible-use statement
Sahayak is an assistive prototype and not an official government service. Final eligibility is decided by the scheme authority.
