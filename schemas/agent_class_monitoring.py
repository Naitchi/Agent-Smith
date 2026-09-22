"""Agent loop configuration and output parameters."""

from dataclasses import dataclass

from .contract_model import LLMProtocol, SandboxProtocol
from .step_metrics import StepMetrics
from .tools.limits import (
    MBPP_MAX_INPUT_TOKENS,
    MBPP_MAX_ITERATIONS,
    MBPP_MAX_OUTPUT_TOKENS,
    MBPP_MAX_WALL_TIME_SECONDS,
)
from .tools.prompts import SYSTEM_PROMPT


class AgentLoopConf:
    """AgentLoop settings; the default limits are the subject's MBPP ones."""

    def __init__(
            self,
            llm: LLMProtocol | None = None,
            sandbox: SandboxProtocol | None = None,
            system_prompt: str = SYSTEM_PROMPT,
            max_iterations: int = MBPP_MAX_ITERATIONS,
            max_input_tokens: int | None = MBPP_MAX_INPUT_TOKENS,
            max_output_tokens: int | None = MBPP_MAX_OUTPUT_TOKENS,
            max_wall_time_seconds: float | None = MBPP_MAX_WALL_TIME_SECONDS,
            api_url: str | None = None,
            api_url_override: str | None = None,
            deadline: float | None = None,
    ):
        from llm import default_model, make_llm
        from src.sandbox import Sandbox

        self.llm = llm if llm is not None else make_llm(default_model())
        self.model_name = self.llm.model
        self.api_url = api_url or getattr(self.llm, "api_url", "")
        self.api_url_override = api_url_override
        self.sandbox = sandbox if sandbox is not None else Sandbox()
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_wall_time_seconds = max_wall_time_seconds
        self.deadline = deadline


@dataclass
class OutputParameter:
    """Values that AgentLoop.build_output turns into a SolutionOutput."""

    task_id: str
    benchmark: str
    success: bool
    solution: str
    iterations: int
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    start: float
    steps: list[StepMetrics]
    message: str | None
