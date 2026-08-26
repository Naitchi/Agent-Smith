from  __future__ import annotations
import time
from schemas import (LLMProtocole, 
                     SandboxProtocol, 
                     SolutionOutput,
                     StepMetrics)
from .agent.parsing import extract_code


class AgentLoop:
    def __init__(
        self,
        llm: LLMProtocole,
        sandbox: SandboxProtocol,
        system_prompt: str,
        max_iteration: int = 10,
        max_input_token: int | None = None,
        max_output_token: int | None = None,
        max_wall_time_seconds: float | None = None,
        model_name: str = "",
        api_url: str = ""
        ) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self.system_prompt = system_prompt
        self.max_iteration = max_iteration
        self.max_input_token = max_input_token
        self.max_output_token = max_output_token
        self.max_wall_time_seconds = max_wall_time_seconds
        self.model_name = model_name
        self.api_url = api_url

        