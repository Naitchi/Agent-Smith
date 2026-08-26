"""Client LLM minimal : messages → texte + usage.

Each provider class stores its model once at construction time and is
callable as `llm(system, messages) -> LLMResult`, which is the shape
`AgentLoop` expects.
"""

import os
import time
from abc import abstractmethod, ABC
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

load_dotenv()
list_possible
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


# class Gene_llm(ABC):
#     def __init__(self, model: str, name: str):
#         self.model = model

    

class GroqLLM:
    def __init__(self, model: str) -> None:
        self.model = model

    def __call__(self, system: str, messages: list[dict]) -> LLMResult:
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


class GeminiLLM:
    def __init__(self, model: str) -> None:
        self.model = model

    def __call__(self, system: str, messages: list[dict]) -> LLMResult:
        start = time.monotonic()
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 2048,
                "tool_choice": None,
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
