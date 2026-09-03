"""Client LLM minimal : messages → texte + usage.

Each provider class stores its model once at construction time and is
callable as `llm(system, messages) -> LLMResult`, which is the shape
`AgentLoop` expects.
"""

import os
import time

import httpx
from dotenv import load_dotenv
from .llm_result import LLMResult

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

class GroqLLM:
    def __init__(self, model: str) -> None:
        self.model = model

    def __call__(
            self, 
            system: str, 
            messages: list[dict]) -> LLMResult:
        start = time.monotonic()
        response = httpx.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 2048,
                "tool_choice": "none",
                "messages": [
                    {
                        "role": "system",
                        "content": system
                        }
                        ] + messages,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        latency_ms = (time.monotonic() - start) * 1000
        body = response.json()
        print(body)
        usage = body.get("usage", {})
        return LLMResult(
            text=body["choices"][0]["message"]["extra_content"],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
        )


class GeminiLLM:
    def __init__(self, model: str) -> None:
        self.model = model

    def __call__(
            self, 
            system: str, 
            messages: list[dict]) -> LLMResult:
        start = time.monotonic()
        response = httpx.post(
            GEMINI_API_URL,
            headers={
                "Authorization": f"Bearer {os.environ['GEMINI_API_KEY']}",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 2048,
                "messages": [
                    {
                        "role": "system", 
                        "content": system
                        }
                        ] + messages,
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
