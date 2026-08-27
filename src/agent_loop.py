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
        start = time.monotonic()
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
            total_input_tokens += result.input_tokens
            total_output_token += result.output_tokens
            message.append(
                {
                    "role": "assistant",
                    "content": result.text
                }
            )
            code = extract_code(result.text)
            final_answer: str | None = None
            if code is None:
                sandbox_input = ""
                sandbox_output = "No valid code block was found in the model's response."
            else:
                sandbox_input = code
                exec_res = self.sandbox.execute(code)
                if exec_res.final_answer is not None:
                    final_answer = exec_res.final_answer
                    sandbox_output = exec_res.stdout or ""
                elif exec_res.error:
                    sandbox_output = f"error: {exec_res.error}"
                else:
                    sandbox_output = exec_res.stdout or "nothing bro"
            message.append(
                {
                    "role": "user",
                    "content": f"observation\n{sandbox_output}"
                }
            )

            steps.append(
                StepMetrics(
                    step=step,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    request_time_ms=request_conv_time,
                    api_url=self.api_url,
                    model_name=self.model_name,
                    llm_output=result.text,
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
            def budget_exceeded() -> str | None:
                if self.max_input_tokens is not None \
                    and total_input_tokens >= self.max_input_tokens:
                    return "max_input_tokens exceeded"
                if self.max_output_tokens is not None \
                    and total_output_token >= self.max_output_tokens:
                    return "max_output_tokens exceeded"
                if (
                    self.max_wall_time_seconds is not None
                    and (time.monotonic() - start) >= self.max_wall_time_seconds
                ):
                    return "max_wall_time_seconds exceeded"
                return None

            error = budget_exceeded()
            if error is not None:
                return self.__output__(
                    task_id,
                    benchmark,
                    False,
                    "",
                    step,
                    total_request,
                    total_input_tokens,
                    total_output_token,
                    start,
                    steps,
                    error
                )

        return self.__output__(
            task_id,
            benchmark,
            False,
            "",
            self.max_iterations,
            total_request,
            total_input_tokens,
            total_output_token,
            start,
            steps,
            "max_iterations reached without final_answer",
        )

    def __output__(
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
        error: str | None,
    ) -> SolutionOutput:
        return SolutionOutput(
            task_id=task_id,
            benchmark=benchmark,
            success=success,
            solution=solution,
            iterations=iterations,
            total_requests=total_requests,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_time_seconds=time.monotonic() - start,
            steps=steps,
            system_prompt=self.system_prompt,
            error=error,
        )
