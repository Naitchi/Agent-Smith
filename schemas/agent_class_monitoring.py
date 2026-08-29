from .contract_model import LLMProtocole, SandboxProtocol
from .step_metrics import StepMetrics


class AgentLoopConf:
    def __init__(
            self,
            llm: LLMProtocole,
            sandbox: SandboxProtocol,
            system_prompt: str,
            max_iterations: int = 10,
            max_input_tokens: int | None = None,
            max_output_tokens: int | None = None,
            max_wall_time_seconds: float | None = None,
            model_name: str = "",
            api_url: str = ""
            ):
        self.llm = llm
        self.sandbox = sandbox
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_wall_time_seconds = max_wall_time_seconds
        self.model_name = model_name
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