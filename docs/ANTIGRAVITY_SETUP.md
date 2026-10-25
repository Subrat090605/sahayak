# Antigravity + Gemini/Groq setup (do this first, ~30 min)

## 1. Install Antigravity
- Download it from Google's official Antigravity page and sign in with your Google account.
- On first launch you can import VS Code/Cursor settings or start fresh.
- The wizard asks how much autonomy agents get. For this project choose a setting where the agent runs routine commands itself but asks before risky ones (option names vary by version). Do not use full "always proceed" if you keep sensitive files nearby.

## 2. Open the project
- Unzip the pack, then **File → Open Folder** → `sahayak`.
- Antigravity reads rules from `AGENTS.md` and `GEMINI.md` in the project root (`GEMINI.md` wins on conflicts). Each rules file is limited to roughly 12,000 characters; ours are far smaller.
- Optional workflows live in `.agent/workflows/` (try typing `/` in the agent panel to see saved workflows such as `/verify` and `/fix`).

## 3. Get API keys
| Provider | Where | Used for |
|---|---|---|
| Gemini | Google AI Studio → Create API key | Primary LLM, document image check |
| Groq | console.groq.com → API Keys | Fast fallback, optional Whisper speech-to-text |

Put both in `.env` (copy from `.env.example`). **Never paste keys into the chat or commit `.env`.**

## 4. Choose models (check the provider model lists; names change)
- Gemini: `gemini-2.5-flash` is a safe default for the free tier.
- Groq text: `llama-3.3-70b-versatile`. Groq vision: `meta-llama/llama-4-scout-17b-16e-instruct`. Groq speech: `whisper-large-v3-turbo`.
- If a model name errors, open the provider's model list and update `.env`. Do not edit code.
- Test Hindi quality on both providers in Phase 3 and set the better one as `LLM_PROVIDER`.

## 5. Free-tier cautions
- Free-tier limits are low and have changed before, so expect 429 errors. Keep both keys set so `llm.py` can fall back to the other provider.
- On Google's free tier, prompts may be used to improve Google's models. **Use fake data only**: no real Aadhaar, phone numbers, or documents, in testing or in your video.
- Cache or keep prompts short during development to save quota.

## 6. Wispr Flow with Antigravity
- Click into the agent panel input, hold your Wispr Flow hotkey, speak, release, read the text, then send.
- If dictation does not appear in a field, click the field once and try again; if it still fails, dictate into any text editor and paste.
- Keep each prompt to one task. Say file names slowly.

## 7. Model choice inside Antigravity
- Antigravity's agent uses its own model (Gemini by default). That is separate from the API keys in `.env`, which your *app* uses.
- If the agent hits its quota, switch to another available model in the model picker.

## 8. Quick checks
- [ ] Antigravity opens the `sahayak` folder and shows AGENTS.md as rules
- [ ] `.env` has at least one working key
- [ ] Wispr Flow types into the agent panel
- [ ] Chrome ready with microphone permission
