"""LLM wrapper supporting Gemini (google-genai) and Groq with automatic fallback.

Provider selection is controlled by LLM_PROVIDER ('gemini' or 'groq').
Handles timeout, retry, JSON mode with fence stripping, and provider failover.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

# Load environment variables without printing or exposing them
load_dotenv()

logger = logging.getLogger("sahayak.llm")


class LLMError(Exception):
    """Custom exception raised when LLM generation fails across providers."""
    pass


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ``` or ``` ... ```) before JSON parsing."""
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        else:
            text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _is_retryable_error(exc: Exception) -> bool:
    """Check if exception represents a rate limit, server error, high demand, or timeout."""
    err_msg = str(exc).lower()
    retryable_patterns = [
        "429",
        "rate limit",
        "resource exhausted",
        "quota",
        "500",
        "502",
        "503",
        "504",
        "unavailable",
        "high demand",
        "spikes in demand",
        "timeout",
        "timed out",
        "connecttimeout",
        "overloaded",
        "connection",
        "service unavailable",
        "servererror",
    ]
    return any(p in err_msg for p in retryable_patterns)


# ---------------------------------------------------------------------------
# Client Factories & Helper Invokers
# ---------------------------------------------------------------------------


def _get_gemini_client(timeout_override: float | None = None):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    from google import genai
    from google.genai import types

    timeout_sec = timeout_override or float(os.getenv("LLM_TIMEOUT", "25.0"))
    http_opts = types.HttpOptions(timeout=timeout_sec)
    return genai.Client(api_key=api_key, http_options=http_opts)


def _call_gemini_generate(client, contents: Any, config: Any) -> Any:
    """Call Gemini generate_content with resilient model selection."""
    env_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    candidates = [env_model, "gemini-3.8-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    seen = set()
    models = [m for m in candidates if not (m in seen or seen.add(m))]

    last_exc = None
    for model in models:
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:
            last_exc = exc
            err_str = str(exc).lower()
            # If the model was retired, deprecated, or not found, try next candidate
            if "not_found" in err_str or "no longer available" in err_str or "404" in err_str:
                continue
            raise
    if last_exc:
        raise last_exc


def _get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    import groq

    timeout_sec = float(os.getenv("LLM_TIMEOUT", "25.0"))
    return groq.Groq(api_key=api_key, timeout=timeout_sec)


def _call_groq_chat(client, messages: list[dict[str, Any]], response_format: dict[str, str] | None = None, temperature: float = 0.2) -> Any:
    """Call Groq chat completions with resilient model selection."""
    env_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    candidates = [env_model, "qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    seen = set()
    models = [m for m in candidates if not (m in seen or seen.add(m))]

    last_exc = None
    for model in models:
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if response_format:
                kwargs["response_format"] = response_format
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            last_exc = exc
            err_str = str(exc).lower()
            if "not found" in err_str or "does not exist" in err_str or "404" in err_str:
                continue
            raise
    if last_exc:
        raise last_exc


# ---------------------------------------------------------------------------
# Execution with 1 Retry + Fallback
# ---------------------------------------------------------------------------


def _execute_with_fallback(
    operation_name: str,
    gemini_func: Callable[[], Any],
    groq_func: Callable[[], Any],
    preferred_provider: str | None = None,
) -> Any:
    """Execute operation on preferred provider with 1 retry, falling back to secondary provider."""
    primary = (preferred_provider or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
    if primary not in {"gemini", "groq"}:
        primary = "gemini"
    secondary = "groq" if primary == "gemini" else "gemini"

    funcs = {"gemini": gemini_func, "groq": groq_func}
    keys = {
        "gemini": os.getenv("GEMINI_API_KEY"),
        "groq": os.getenv("GROQ_API_KEY"),
    }

    errors: list[str] = []

    # Attempt on primary provider
    if keys.get(primary):
        for attempt in range(1, 3):  # initial attempt + 1 retry
            try:
                return funcs[primary]()
            except Exception as exc:
                errors.append(f"{primary} (attempt {attempt}): {type(exc).__name__} - {exc}")
                if attempt == 1 and _is_retryable_error(exc):
                    time.sleep(1.0)
                    continue
                break
    else:
        errors.append(f"{primary}: No API key configured")

    # Attempt fallback to secondary provider if key exists
    if keys.get(secondary):
        logger.warning(
            "Primary LLM provider '%s' failed for %s. Falling back to '%s'.",
            primary,
            operation_name,
            secondary,
        )
        for attempt in range(1, 3):
            try:
                return funcs[secondary]()
            except Exception as exc:
                errors.append(f"{secondary} fallback (attempt {attempt}): {type(exc).__name__} - {exc}")
                if attempt == 1 and _is_retryable_error(exc):
                    time.sleep(1.0)
                    continue
                break
    else:
        errors.append(f"{secondary}: No fallback API key configured")

    raise LLMError(f"All LLM attempts failed for {operation_name}. Details: {'; '.join(errors)}")


# ---------------------------------------------------------------------------
# Public Functions
# ---------------------------------------------------------------------------


def generate_text(
    prompt: str,
    system_prompt: str | None = None,
    provider: str | None = None,
    temperature: float = 0.2,
) -> str:
    """Generate plain text completion using configured provider with fallback."""

    def call_gemini() -> str:
        client = _get_gemini_client()
        if not client:
            raise ValueError("GEMINI_API_KEY is not set")
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_prompt if system_prompt else None,
        )
        response = _call_gemini_generate(client, prompt, config)
        text = response.text or ""
        return text.strip()

    def call_groq() -> str:
        client = _get_groq_client()
        if not client:
            raise ValueError("GROQ_API_KEY is not set")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = _call_groq_chat(client, messages, temperature=temperature)
        text = response.choices[0].message.content or ""
        return text.strip()

    return _execute_with_fallback("generate_text", call_gemini, call_groq, preferred_provider=provider)


def generate_json(
    prompt: str,
    system_prompt: str | None = None,
    provider: str | None = None,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Generate structured JSON response using JSON mode and strip code fences before parsing."""

    def call_gemini() -> dict[str, Any]:
        client = _get_gemini_client()
        if not client:
            raise ValueError("GEMINI_API_KEY is not set")
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            system_instruction=system_prompt if system_prompt else None,
        )
        response = _call_gemini_generate(client, prompt, config)
        raw_text = response.text or ""
        clean_text = strip_code_fences(raw_text)
        return json.loads(clean_text)

    def call_groq() -> dict[str, Any]:
        client = _get_groq_client()
        if not client:
            raise ValueError("GROQ_API_KEY is not set")

        sys_instruction = system_prompt or "You are a JSON extractor. Output valid JSON only."
        if "json" not in sys_instruction.lower():
            sys_instruction += " Always respond in valid JSON format."

        messages = [
            {"role": "system", "content": sys_instruction},
            {"role": "user", "content": prompt},
        ]

        response = _call_groq_chat(client, messages, response_format={"type": "json_object"}, temperature=temperature)
        raw_text = response.choices[0].message.content or ""
        clean_text = strip_code_fences(raw_text)
        return json.loads(clean_text)

    return _execute_with_fallback("generate_json", call_gemini, call_groq, preferred_provider=provider)


def describe_image(
    image: bytes | str | Path,
    prompt: str = "Describe this document, identifying the document type and any key fields.",
    mime_type: str | None = None,
    provider: str | None = None,
) -> str:
    """Analyze and describe an image/document using vision models with fallback."""
    if isinstance(image, (str, Path)):
        img_path = Path(image)
        with open(img_path, "rb") as f:
            image_bytes = f.read()
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(str(img_path))
    else:
        image_bytes = image

    resolved_mime = mime_type or "image/jpeg"

    def call_gemini() -> str:
        client = _get_gemini_client(timeout_override=float(os.getenv("VISION_TIMEOUT", "3.0")))
        if not client:
            raise ValueError("GEMINI_API_KEY is not set")
        from google.genai import types

        part = types.Part.from_bytes(data=image_bytes, mime_type=resolved_mime)
        return _call_gemini_generate(client, [part, prompt], None).text.strip()

    def call_groq() -> str:
        client = _get_groq_client()
        if not client:
            raise ValueError("GROQ_API_KEY is not set")

        vision_model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{resolved_mime};base64,{b64_img}"

        response = client.chat.completions.create(
            model=vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        )
        return (response.choices[0].message.content or "").strip()

    return _execute_with_fallback("describe_image", call_gemini, call_groq, preferred_provider=provider)
