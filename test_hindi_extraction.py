"""Compare Hindi profile field extraction between Gemini and Groq.

Sentence: "मैं उन्नाव का किसान हूँ, मेरे पास दो एकड़ ज़मीन है"
Expected fields (DATA_SCHEMA.md):
- district: "Unnao"
- occupation: "farmer"
- land_acres: 2.0
"""

import io
import json
import sys
import time

import llm

PROMPT = """
You are a data extraction assistant for an Indian citizen welfare service.
Extract profile fields from this user statement:
"मैं उन्नाव का किसान हूँ, मेरे पास दो एकड़ ज़मीन है"

Return a JSON object containing only standard fields from this schema:
- name (string or null)
- age (integer or null)
- gender (string: "male" / "female" / "other" or null)
- state (string or null)
- district (string or null)
- occupation (string: "farmer", "student", "labourer", "salaried", "self_employed", "unemployed", "other" or null)
- land_acres (float or null)
- annual_income (integer or null)
- category (string: "general", "obc", "sc", "st" or null)
- bpl_household (boolean or null)
- has_lpg_connection (boolean or null)
- detected_language (string: "hi" or "en")

Do not guess or invent fields not mentioned. Omit or set null for fields not stated.
"""


def run_provider_test(provider_name: str) -> dict | None:
    print(f"\n{'=' * 50}")
    print(f"Testing Provider: {provider_name.upper()}")
    print(f"{'=' * 50}")

    start_time = time.time()
    try:
        # Call provider directly without fallback to isolate comparison
        if provider_name == "gemini":
            client = llm._get_gemini_client()
            if not client:
                print("[ERROR] GEMINI_API_KEY is not set.")
                return None
            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            )
            resp = llm._call_gemini_generate(client, PROMPT, config)
            extracted = json.loads(llm.strip_code_fences(resp.text))
        elif provider_name == "groq":
            client = llm._get_groq_client()
            if not client:
                print("[ERROR] GROQ_API_KEY is not set.")
                return None
            messages = [
                {"role": "system", "content": "You are a JSON data extractor. Output valid JSON only."},
                {"role": "user", "content": PROMPT},
            ]
            resp = llm._call_groq_chat(client, messages, response_format={"type": "json_object"}, temperature=0.1)
            extracted = json.loads(llm.strip_code_fences(resp.choices[0].message.content))
        else:
            raise ValueError(f"Unknown provider {provider_name}")

        duration = time.time() - start_time
        print(f"Time taken: {duration:.2f} seconds")
        print("Extracted JSON:")
        print(json.dumps(extracted, indent=2, ensure_ascii=False))
        return extracted
    except Exception as exc:
        duration = time.time() - start_time
        print(f"Failed in {duration:.2f}s: {type(exc).__name__}: {exc}")
        return None


def main():
    print("Evaluating Hindi sentence:")
    print('"मैं उन्नाव का किसान हूँ, मेरे पास दो एकड़ ज़मीन है"')

    gemini_result = run_provider_test("gemini")
    groq_result = run_provider_test("groq")

    print(f"\n{'=' * 50}")
    print("COMPARISON SUMMARY")
    print(f"{'=' * 50}")
    print(f"Gemini output: {gemini_result}")
    print(f"Groq output:   {groq_result}")


if __name__ == "__main__":
    main()
