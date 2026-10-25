# Voice prompt script for Wispr Flow (start → finish)

## How to use
1. Open the project folder in **Antigravity** (see `docs/ANTIGRAVITY_SETUP.md`). Use the agent panel in the Editor view.
2. Click into the chat box, hold your Wispr Flow hotkey, and **speak the prompt** (do not type).
3. Read the transcribed text once. Fix names or file paths by voice if they are wrong, then send.
4. After each prompt, check the **✔ Check** line before moving on. Commit when it passes.
5. If something breaks, dictate: *"Run it, read the error, and fix it. Explain the fix in two lines."*

**Speaking tips:** say file names slowly ("main dot py", "schemes dot json"); say "new line" for line breaks if needed; speak one task per prompt; end with "run it and fix any errors."

---

## Phase 0 — Project context (do this first)

**P0.1** Read the files AGENTS dot md, GEMINI dot md, docs slash PRD dot md, docs slash ARCHITECTURE dot md and docs slash DATA SCHEMA dot md. Summarize the project in five lines and list the files we need to create. Do not write code yet.
✔ Check: the summary matches Sahayak (voice, 5 agents, rules in code).

**P0.2** Create a Python virtual environment, install everything from requirements dot txt, and create an empty tests folder init file. Tell me the command to activate the environment.
✔ Check: `pip list` shows fastapi, anthropic, pytest.

**P0.3** Create main dot py with a FastAPI app. Add a health endpoint that returns status ok. Serve the static folder at the root. Load the environment file with python dash dotenv. Run it with uvicorn and give me the URL.
✔ Check: `/health` returns `{"status":"ok"}`.

**P0.4** Initialize git, make a first commit with the message "project setup", and show me the git log.

---

## Phase 1 — Verified scheme data (you verify, voice edits)

**P1.1** Copy data slash schemes dot template dot json to data slash schemes dot json. Fill it with four schemes: PM Kisan, Ayushman Bharat PM JAY, PM Ujjwala Yojana, and one national scholarship scheme for students. Follow the schema in docs slash DATA SCHEMA dot md. Put the value TODO wherever you are not certain, and never guess numbers, dates or links.
✔ Check: file opens, valid JSON.

**P1.2 (manual, ~45 min)** Open each scheme's official portal. For each scheme, verify eligibility rules, required documents, benefit text and official link. Then dictate corrections one at a time, for example:
*"In schemes dot json, for the scheme with id pm dash kisan, change the official link to <paste link>, set last verified to today's date, and set source note to the official page I used."*
Repeat until no `TODO` remains in rules that matter for your demo.
✔ Check: every scheme has `last_verified` and `source_note`.

**P1.3** Add a small script called validate underscore data dot py that loads schemes dot json, checks every scheme has the required keys from the schema, lists any remaining TODO values, and exits with an error if keys are missing. Run it.
✔ Check: script prints a clean report.

**P1.4** Commit with the message "add verified scheme data".

---

## Phase 2 — Eligibility engine (no LLM)

**P2.1** Create eligibility dot py. Write a function evaluate scheme that takes a user profile dictionary and one scheme, and returns the structure described in docs slash DATA SCHEMA dot md: status, reasons met, reasons failed and missing fields. Support the operators eq, ne, in, lte, gte, between, is true and is false. If a rule value is TODO or the profile field is missing, treat it as maybe. Use the Hindi and English labels as reasons.

**P2.2** Add a function evaluate all that runs evaluate scheme for every scheme and returns results sorted: eligible first, then maybe, then not eligible.

**P2.3** Create tests slash test underscore eligibility dot py with the five profiles from docs slash TESTING dot md, plus tests for missing fields, TODO values and unknown fields. Run pytest and fix failures.
✔ Check: all tests pass. If a test expectation contradicts the official rules you verified, fix the **scheme data**, not the test.

**P2.4** Commit with the message "eligibility engine with tests".

---

## Phase 3 — LLM wrapper and agents

**P3.1** Create llm dot py that supports two providers chosen by the environment variable LLM underscore PROVIDER: gemini using the google dash genai package, and groq using the groq package. Expose three functions: generate text, generate json, and describe image. Read keys and model names from the environment file. Add a timeout, one retry, and automatic fallback to the other provider if the first one fails with a rate limit or server error and the other key exists. For JSON, use the JSON mode of each provider and strip code fences before parsing. Raise a clear custom error if both fail.
✔ Check: a tiny script calls generate text on each provider and prints the reply.

**P3.1b** Write a small test script that sends the Hindi sentence "मैं उन्नाव का किसान हूँ, मेरे पास दो एकड़ ज़मीन है" to each provider's generate json function and prints the extracted fields. Compare the two and tell me which handles Hindi better; I will set LLM underscore PROVIDER accordingly.

**P3.2** In agents dot py, build the Profile Agent. It takes the user's message in Hindi, English or mixed, the existing profile, and returns updated profile fields as JSON using only the fields in docs slash DATA SCHEMA dot md. It must not guess values the user did not say. Also detect the user's language as hi or en.

**P3.3** Add a function in agents dot py that, given the profile and the schemes, returns the list of missing required fields, ordered by importance. Then build the Eligibility Agent: if fields are missing, ask exactly one short follow-up question in the user's language; otherwise call evaluate all and explain the results in simple language.

**P3.4** Add the guardrail: the Eligibility Agent may only use facts from schemes dot json. Never invent amounts, dates, rules or links. Every scheme mentioned must include its official link and one line saying to verify on the official portal. Put this in the system prompt and add a test with a mocked model.

**P3.5** Create coordinator dot py with an in-memory session store and the state machine from docs slash ARCHITECTURE dot md. It should run the right agent for the current state, record a trace entry with agent name, action and milliseconds for every step, and support the phrase "start over".

**P3.6** In main dot py add the chat endpoint described in docs slash ARCHITECTURE dot md. It accepts session id, message and language, calls the coordinator, and returns reply, language, state, matches and trace. Add friendly error handling if the model call fails.

**P3.7** Write a terminal script called chat underscore cli dot py that lets me chat with the endpoint so I can test without the browser. Run it with the Unnao farmer example: "I am a farmer in Unnao with two acres."
✔ Check: agent asks one follow-up, then returns matches with reasons and links.

**P3.8** Commit with the message "agents and coordinator".

---

## Phase 4 — Voice UI

**P4.1** Create static slash index dot html as one mobile friendly page, with a clean modern design. It needs a large mic button, a Hindi and English toggle, chat bubbles, a text box fallback, and a side panel titled "Agents at work" that shows the live trace from the chat endpoint. Use vanilla JavaScript only.

**P4.2** Add speech recognition using the browser Web Speech API with language hi dash IN or en dash IN based on the toggle. Show the live transcript, send the final transcript to the chat endpoint, and display the reply. If the API is not supported, hide the mic and show a message.

**P4.3** Add spoken replies with speech synthesis using the matching language voice. Add a mute button. Stop speaking when the user starts talking.

**P4.4** Show matched schemes as cards with status badge, reason, benefit and official link button. Add loading states and friendly error messages.
✔ Check: speak the Unnao farmer sentence in Chrome and see cards + trace.

**P4.5** Commit with the message "voice UI".

---

## Phase 5 — Document agent

**P5.1** In agents dot py build the Document Agent. For a chosen scheme, return the checklist from schemes dot json in simple language with where to get each document, in the user's language. No invented documents.

**P5.2** Add a button on each scheme card called "What documents do I need?" that shows the checklist with checkboxes.

**P5.3** Add the upload dash doc endpoint. It accepts an image, sends it to the vision model of the active provider (Gemini, or the Groq vision model from the environment file), and returns the likely document type, whether it matches an item in the checklist, and whether the name looks readable. Process in memory only, never save the file. Mask any ID number except the last four digits in everything returned or logged.

**P5.4** Add an upload button in the UI that ticks the matching checklist item and shows any warning.
✔ Check: upload a fake or sample document image and see the checkbox tick.

**P5.5** Commit with the message "document agent".

---

## Phase 6 — Form and reminders

**P6.1** Build the Form Agent and a form endpoint that returns a printable HTML page with the user's details, the scheme name, the document checklist, the official link, and a note saying "Draft prepared by Sahayak. Submit on the official portal." Add print CSS so it fits one A4 page and renders Hindi text correctly.

**P6.2** Add a "Download PDF" button that opens the form page and triggers the browser print dialog so the user can save as PDF.

**P6.3** Build the Follow-up Agent and a reminders dot ics endpoint that generates a calendar file with reminders at three days for collecting documents, seven days for submitting, and thirty days for checking status. Use a real deadline only if schemes dot json contains one; never invent deadlines.

**P6.4** Add buttons for "Download reminders" and wire both outputs into the chat flow after the user picks a scheme.
✔ Check: PDF prints with Hindi text; `.ics` opens in your calendar.

**P6.5** Commit with the message "form and reminders".

---

## Phase 7 — Reliability and demo mode

**P7.1** Add failure handling everywhere: model errors, timeouts, empty speech, unsupported browser, unclear language. Each should show a friendly message and fall back to text input. Add a retry button.

**P7.2** Add a demo mode button that loads the sample farmer profile through the demo load endpoint and plays the full flow without needing speech.

**P7.3** Add a footer disclaimer: "Sahayak is a prototype, not an official government service. Verify on the official portal."

**P7.4** Run all tests and the seven manual scenarios from docs slash TESTING dot md. List any failures and fix only the ones that break the main flow.

**P7.5** Update README dot md with real setup steps, screenshots placeholders, and the final list of agents. Make sure the Mermaid diagram in docs slash ARCHITECTURE dot md matches the code. Commit with the message "reliability and docs".

---

## Phase 8 — Record, polish, submit

**P8.1 (manual)** Follow the video script in `docs/TESTING.md`. Use fake data only. Record two takes.

**P8.2 (manual)** Fill the links and final text in `docs/SUBMISSION.md`.

**P8.3** Push to GitHub, check the README renders, make sure `.env` is not committed, and tag the release v1.

**P8.4 (stretch)** Deploy to Render or Railway with environment variables set, and add the live link to the README.

---

## Optional upgrade — Groq Whisper speech-to-text
**U1** Add a transcribe endpoint that accepts a short audio recording, sends it to Groq's speech-to-text model from the environment file, and returns the text. Add a toggle in the UI "Use server speech recognition" that records with the browser MediaRecorder, posts the audio, and uses the returned text as the user's message. Keep the browser speech recognition as the default.
✔ Check: compare Hindi accuracy against the browser mic; keep whichever is better.

---

## Emergency prompts (dictate when stuck)
- "Run the app, read the full error, find the root cause and fix it. Do not change unrelated files."
- "The mic does not work in Chrome. Add logging and show the exact reason on screen."
- "The Hindi text in the PDF is broken. Fix the fonts and the print CSS."
- "Make the reply shorter and simpler for a low literacy user."
- "We hit a 429 rate limit. Make llm dot py back off, fall back to the other provider, and show a friendly message if both are limited."
- "We are short on time. List the three smallest changes that make the demo reliable."
