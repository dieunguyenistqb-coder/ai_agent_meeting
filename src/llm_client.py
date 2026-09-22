import json
import os
from pathlib import Path
from dotenv import load_dotenv
from .request_context import current_request, usage_counts

load_dotenv()

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "prompt_v1.txt"

def _build_user_prompt(payload: dict) -> str:
    transcript_lines = payload["transcript"]

    evidence = json.dumps(
        payload.get("meeting_date_evidence"),
        ensure_ascii=False
    )

    return f"""meeting_id: {payload["meeting_id"]}
meeting_date: {payload.get("meeting_date") or "null"}
meeting_date_evidence: {evidence}

Transcript:
{transcript_lines}
"""

def call_llm(payload: dict) -> str:
    provider = "gemini" if current_request.get() is not None else os.getenv("LLM_PROVIDER", "gemini").lower().strip()
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_prompt = _build_user_prompt(payload)

    if provider == "gemini":
        return _call_gemini(system_prompt, user_prompt)

    if provider == "openai":
        return _call_openai(system_prompt, user_prompt)

    raise ValueError("LLM_PROVIDER phải là 'gemini' hoặc 'openai'.")

def _call_gemini(system_prompt: str, user_prompt: str) -> str:
    from google import genai

    context = current_request.get()
    api_key = context.api_key if context else os.getenv("GEMINI_API_KEY")
    model = context.model if context else os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY trong file .env")

    options = {}
    if context:
        context.on_request()
        # Web requests are bounded; application retry policy remains in pipeline.
        options['http_options'] = {'timeout': context.timeout_ms, 'retry_options': {'attempts': 1}}
    client = genai.Client(api_key=api_key, **options)

    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config={
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
            "temperature": 0,
        },
    )
    if context:
        context.on_usage(usage_counts(getattr(response, 'usage_metadata', None)))
    return response.text

def _call_openai(system_prompt: str, user_prompt: str) -> str:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-5.6")

    if not api_key:
        raise RuntimeError("Thiếu OPENAI_API_KEY trong file .env")

    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model=model,
        instructions=system_prompt,
        input=user_prompt,
    )
    return response.output_text
