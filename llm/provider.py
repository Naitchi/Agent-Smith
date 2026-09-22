"""LLM provider interface and its OpenAI-compatible HTTP implementation."""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from dotenv import load_dotenv

from schemas.llm_result import LLMResult
from schemas.tools.limits import (
    CHARS_PER_TOKEN,
    DEFAULT_TEMPERATURE,
    MAX_TOKENS_PER_REQUEST,
    REQUEST_TIMEOUT_SECONDS,
)

load_dotenv()

DEFAULT_MAX_TOKENS = MAX_TOKENS_PER_REQUEST


def rejected_generation(response: httpx.Response) -> str | None:
    """Recover a native tool call Groq rejected, as a <tool_call> block."""
    if response.status_code != 400:
        return None
    try:
        error = response.json().get("error", {})
    except ValueError:
        return None
    if (error.get("code") != "tool_use_failed"
            or not error.get("failed_generation")):
        return None
    return f"<tool_call>{error['failed_generation']}</tool_call>"


class LLMProvider(ABC):
    """Common interface for every LLM provider."""

    model: str
    api_url: str
    api_key_env: str

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict],
        stop: list[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> LLMResult:
        """Run one completion and return its text and token usage."""

    def __call__(
        self,
        system: str,
        messages: list[dict],
        stop: list[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> LLMResult:
        """Call `complete`, matching the LLMProtocol signature."""
        return self.complete(
            system,
            messages,
            stop=stop,
            max_tokens=max_tokens,
            temperature=temperature,
        )


class OpenAICompatibleProvider(LLMProvider):
    """Any provider exposing an OpenAI-style /chat/completions endpoint."""

    def __init__(
        self,
        model: str,
        api_url: str,
        api_key_env: str,
        extra_payload: dict[str, Any] | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.api_url = api_url
        self.api_key_env = api_key_env
        self.extra_payload = extra_payload or {}
        self.timeout = timeout

    def complete(
        self,
        system: str,
        messages: list[dict],
        stop: list[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> LLMResult:
        """Call the endpoint with the key currently set in os.environ."""
        key = os.environ.get(self.api_key_env, "").split(",")[0].strip()
        if not key:
            raise RuntimeError(
                f"{self.api_key_env} absente de l'environnement :"
                f" impossible d'interroger {self.model}."
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}] + messages,
            **self.extra_payload,
        }
        if stop:
            payload["stop"] = stop

        start = time.monotonic()
        response = httpx.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {key}",
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000
        recovered = rejected_generation(response)
        if recovered is not None:
            chars = sum(len(m["content"]) for m in payload["messages"])
            return LLMResult(
                text=recovered,
                input_tokens=chars // CHARS_PER_TOKEN,
                output_tokens=len(recovered) // CHARS_PER_TOKEN,
                latency_ms=latency_ms,
                model_name=self.model,
                api_url=self.api_url,
            )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage", {})
        return LLMResult(
            text=body["choices"][0]["message"].get("content") or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            model_name=self.model,
            api_url=self.api_url,
        )

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider({self.model!r}, {self.api_url!r})"
