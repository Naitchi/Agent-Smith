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
        max_iterations: int = 10,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        max_wall_time_seconds: float | None = None,
        model_name: str = "",
        api_url: str = ""
        ) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_wall_time_seconds = max_wall_time_seconds
        self.model_name = model_name
        self.api_url = api_url


    def run(
            self, 
            task_id: str, 
            benchmark: str, 
            user_prompt:str) -> SolutionOutput:
        start = time.monotonic
        message: list[dict] = [
            {
                "role": "user",
                "content": user_prompt
            }
        ]

        steps: list[StepMetrics] = []
        total_input_tokens = 0
        total_output_token = 0
        total_request = 0
        for step in range(1, self.max_iterations + 1):
            request_start = time.monotonic()
            result = self.llm(self.system_prompt, message)
            request_conv_time = (time.monotonic() - request_start) * 1000

            total_request += 1
            total_input_tokens += result.input_token
            total_output_token += result.output_token
            message.append(
                {
                    "role": "assistant",
                    "content": result.text
                }
            )
            code = extract_code(result.txt)
            final_answer: str | None = None
            if code is None:
                sandbox_input = ""
                sandbox_output = "no code was found sorry"
            else:
                sandbox_input = code
                exec_res = self.sandbox.execute(code)
                if exec_res.final_answer is not None:
                    final_answer = exec_res.final_answer
                    sandbox_output = exec_res.stdout or ""
                elif exec_res.error:
                    sandbox_output = f"error {exec_res.error}"
                else:
                    sandbox_output = exec_res.stdout or "nothing bro"
            message.append([
                {
                    "role": "user",
                    "content": f"observation\n{sandbox_output}"
                }
            ])

            steps.append(
                StepMetrics
                (
                    step=step,
                    input_token=result.input_tokens,
                    output_token=result.output_tokens,
                    time_ml=request_conv_time,
                    api_url=self.api_url,
                    model_name=self.model_name,
                    llm_output=result,
                    sandbox_input=sandbox_input,
                    sandbox_output=sandbox_output,
                    retries=0
                    )
                )
            if final_answer is not None:
                return self.__output__(
                    task_id,
                    benchmark,
                    True,
                    final_answer,
                    step,
                    total_request,
                    total_input_tokens,
                    total_output_token,
                    start,
                    steps,
                    None
                )
            

