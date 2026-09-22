import random
from dataclasses import dataclass

from .contract_model import LLMProtocole, SandboxProtocol
from .step_metrics import StepMetrics
from .tools.limits import (
    MBPP_MAX_INPUT_TOKENS,
    MBPP_MAX_ITERATIONS,
    MBPP_MAX_OUTPUT_TOKENS,
    MBPP_MAX_WALL_TIME_SECONDS,
)
from .tools.prompts import SYSTEM_PROMPT
from .tools.tools_agent import AUTHORIZED_GEMINI


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
            max_iterations: int = MBPP_MAX_ITERATIONS,
            max_input_tokens: int | None = MBPP_MAX_INPUT_TOKENS,
            max_output_tokens: int | None = MBPP_MAX_OUTPUT_TOKENS,
            max_wall_time_seconds: float | None = MBPP_MAX_WALL_TIME_SECONDS,
            models_name: list[str] = AUTHORIZED_GEMINI,
            api_url: str | None = None,
            deadline: float | None = None,
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
        # Instant `time.monotonic()` ou le PROCESS doit avoir rendu la main
        # (la moulinette compte depuis son lancement, pas depuis `run()`).
        self.deadline = deadline


@dataclass
class OutputParameter:
    """Ce que `AgentLoop._output()` met en forme en `SolutionOutput`.

    `start` est l'instant `time.monotonic()` du debut de la boucle : la duree
    totale est calculee au moment de la sortie. `message` devient `error`.
    """

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
