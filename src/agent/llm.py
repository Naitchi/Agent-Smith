"""Client LLM minimal : messages → texte + usage."""

import os
import time
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


def groq_complete(model: str, system: str, messages: list[dict]) -> LLMResult:
    start = time.monotonic()
    response = httpx.post(
        GROQ_API_URL,
        headers={
            "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2048,
            "messages": [{"role": "system", "content": system}] + messages,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    latency_ms = (time.monotonic() - start) * 1000
    body = response.json()
    usage = body.get("usage", {})
    return LLMResult(
        text=body["choices"][0]["message"]["content"],
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        latency_ms=latency_ms,
    )
