import random

from .contract_model import LLMProtocole, SandboxProtocol
from .step_metrics import StepMetrics
from .tools_agent import AUTHORIZED_GEMINI, SYSTEM_PROMPT


class AgentLoopConf:
    """Conf d'`AgentLoop`. Limites par defaut = celles du sujet pour MBPP.

    `model_name` et `api_url` sont derives du llm, jamais regles a part.
    `llm` et `src.sandbox` sont importes dans `__init__` : au niveau module,
    ils feraient un cycle avec `schemas`.
    """

    def __init__(
            self,
            llm: LLMProtocole | None = None,
            sandbox: SandboxProtocol | None = None,
            system_prompt: str = SYSTEM_PROMPT,
            max_iterations=10,
            max_input_tokens=6_000,
            max_output_tokens=1_500,
            max_wall_time_seconds=120,
            models_name: list[str] = AUTHORIZED_GEMINI,
            api_url: str | None = None
            ):
        from llm import make_llm
        from src.sandbox import Sandbox

        self.llm = llm if llm is not None else make_llm(random.choice(models_name))
        self.model_name = self.llm.model
        self.api_url = api_url or getattr(self.llm, "api_url", "")
        self.sandbox = sandbox if sandbox is not None else Sandbox()
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_wall_time_seconds = max_wall_time_seconds


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