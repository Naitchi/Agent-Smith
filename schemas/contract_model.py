"""Interfaces between the agent loop, the LLM and the sandbox."""

from typing import Protocol

from pydantic import BaseModel

from .llm_result import LLMResult


class ExecutionResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    final_answer: str | None = None
    timed_out: bool = False
    truncated: bool = False
    duration_ms: float = 0.0


class SandboxProtocol(Protocol):
    def execute(self, code: str) -> ExecutionResult:
        ...

    def get_manual(self) -> str:
        ...

    def close(self) -> None:
        ...


class LLMProtocol(Protocol):
    """What the agent loop needs from a provider, whichever it is."""

    model: str
    api_url: str
    api_key_env: str

    def __call__(
        self,
        system: str,
        messages: list[dict],
        stop: list[str] | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> LLMResult:
        ...
