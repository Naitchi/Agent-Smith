from  __future__ import annotations
import time, json, os, shutil
from pathlib import Path
from schemas import (AgentLoopConf,
                     OutputParameter,
                     SolutionOutput,
                     StepMetrics)
from .agent.parsing import extract_code


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT_ROOT / "backup_memory"
BACKUP_FILE = BACKUP_DIR / "backup.json"
MAX_CONSECUTIVE_ERRORS = 3


def backup_json(total_input_tokens: int, total_output_token: int, total_request: int):
    try:
        os.mkdir(BACKUP_DIR)
    except FileExistsError:
        shutil.rmtree(BACKUP_DIR)
        os.mkdir(BACKUP_DIR)
    with open(BACKUP_FILE, "w") as f:
        json.dump(
            {
                "total_input_tokens": total_input_tokens,
                "total_output_token": total_output_token,
                "total_request": total_request,
            },
            f,
            indent=2,
        )


def clear_backup():
    BACKUP_FILE.unlink(missing_ok=True)


def init_value() -> tuple[int, int, int]:
    if not BACKUP_FILE.exists() or BACKUP_FILE.stat().st_size == 0:
        return 0, 0, 0
    with open(BACKUP_FILE) as f:
        res = json.load(f)
    return (
        res.get("total_input_tokens", 0),
        res.get("total_output_token", 0),
        res.get("total_request", 0),
    )

class AgentLoop:
    def __init__(
        self,
        agent_loop_conf: AgentLoopConf
        ) -> None:
        self.agent_loop = agent_loop_conf


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
        total_input_tokens, total_output_token, total_request = init_value()
        error: str | None = None
        last_error: str | None = None
        consecutive_errors = 0
        for step in range(1, self.agent_loop.max_iterations + 1):
            try:
                request_start = time.monotonic()
                result = self.agent_loop.llm(self.agent_loop.system_prompt, message)
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
                    exec_res = self.agent_loop.sandbox.execute(code)
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
                        api_url=self.agent_loop.api_url,
                        model_name=self.agent_loop.model_name,
                        llm_output=result.text,
                        sandbox_input=sandbox_input,
                        sandbox_output=sandbox_output,
                        retries=0
                        )
                    )
                if final_answer is not None:
                    clear_backup()
                    return self.__output__(
                        OutputParameter(
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
                    )
                consecutive_errors = 0
                error = self.budget_exceeded(start, total_input_tokens, total_output_token)
                if error is not None:
                    break
            except KeyboardInterrupt:
                backup_json(total_input_tokens, total_output_token, total_request)
                raise
            except Exception as e:
                backup_json(total_input_tokens, total_output_token, total_request)
                print(f"Error: {e}")
                last_error = f"{type(e).__name__}: {e}"
                consecutive_errors += 1

                error = self.budget_exceeded(start, total_input_tokens, total_output_token)
                if error is not None:
                    break
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    error = (
                        f"{MAX_CONSECUTIVE_ERRORS} erreurs consecutives, "
                        f"derniere -> {last_error}"
                    )
                    break
        final_error = (
            error or last_error or "max_iterations reached without final_answer"
        )
        return self.__output__(
            OutputParameter(
                task_id,
                benchmark,
                False,
                "",
                len(steps),
                total_request,
                total_input_tokens,
                total_output_token,
                start,
                steps,
                final_error
            )
        )

    def budget_exceeded(
            self, 
            start: float, 
            total_input_tokens: int, 
            total_output_token: int) -> str | None:
        if (self.agent_loop.max_input_tokens is not None
            and total_input_tokens >= self.agent_loop.max_input_tokens):
            return "max_input_tokens exceeded"
        if (self.agent_loop.max_output_tokens is not None
            and total_output_token >= self.agent_loop.max_output_tokens):
            return "max_output_tokens exceeded"
        if (
             self.agent_loop.max_wall_time_seconds is not None
             and (time.monotonic() - start) >= self.agent_loop.max_wall_time_seconds
             ):
             return "max_wall_time_seconds exceeded"
        return None

    def __output__(
        self,
        output_conf: OutputParameter
    ) -> SolutionOutput:
        return SolutionOutput(
            task_id=output_conf.task_id,
            benchmark=output_conf.benchmark,
            success=output_conf.success,
            solution=output_conf.solution,
            iterations=output_conf.iterations,
            total_requests=output_conf.total_requests,
            total_input_tokens=output_conf.total_input_tokens,
            total_output_tokens=output_conf.total_output_tokens,
            total_time_seconds=time.monotonic() - output_conf.start,
            steps=output_conf.steps,
            system_prompt=self.agent_loop.system_prompt,
            error=output_conf.message,
        )
