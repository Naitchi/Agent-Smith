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
    def execute(self, code: str) -> ExecutionResult: ...
    def get_manual(self) -> str: ...
    def close(self) -> None: ...


class LLMProtocole(Protocol):
    def __call__(self, system: str, messages: list[dict]) -> LLMResult: ...