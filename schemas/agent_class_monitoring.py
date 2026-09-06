from .contract_model import LLMProtocole, SandboxProtocol
from .tools_agent import (AUTHORIZED_GEMINI, 
                          GEMINI_API_URL, 
                          SYSTEM_PROMPT)
from .llmclass import GeminiLLM
import random
from .step_metrics import StepMetrics


class AgentLoopConf:
    def __init__(
            self,
            llm: LLMProtocole | None = None,
            sandbox: SandboxProtocol | None = None,
            system_prompt: str = SYSTEM_PROMPT,
            max_iterations=45,
            max_input_tokens=11000000,
            max_output_tokens=15000000,
            max_wall_time_seconds=1200000,
            models_name: list[str] = AUTHORIZED_GEMINI,
            api_url: str = GEMINI_API_URL
            ):
        from src.sandbox import Sandbox

        self.model_name = random.choice(models_name)
        self.llm = GeminiLLM("gemini-3.1-flash-lite")
        self.sandbox = sandbox if sandbox is not None else Sandbox()
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_wall_time_seconds = max_wall_time_seconds
        self.api_url = api_url


class OutputParameter:
    def __init__(
            self,
            task_id: str,
            benchmark: str,
            success: bool,
            solution: str,
            iterations: int,
            total_requests: int,
            total_input_tokens: int,
            total_output_tokens: int,
            start: float,
            steps: list[StepMetrics],
            message: str | None):
        self.task_id = task_id
        self.benchmark = benchmark
        self.success = success
        self.solution = solution
        self.iterations = iterations
        self.total_requests = total_requests
        self.total_input_tokens = total_input_tokens
        self.total_output_tokens = total_output_tokens
        self.start = start
        self.steps = steps
        self.message = message