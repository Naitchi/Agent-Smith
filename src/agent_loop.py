"""Thought / Code / Observation loop driving the LLM and the sandbox."""

from __future__ import annotations

import json
import re
import time

import httpx

from llm import TokenRotator, make_llm
from schemas import (
    STOP_SEQUENCES,
    AgentLoopConf,
    AgentLoopError,
    ConsecutiveErrorsError,
    ExecutionResult,
    MaxInputTokensError,
    MaxIterationsError,
    MaxOutputTokensError,
    MaxWallTimeError,
    NoModelAvailableError,
    OutputParameter,
    SigStopError,
    SolutionOutput,
    StepMetrics,
    create_newcontext,
    extract_code,
)
from schemas.llm_result import LLMResult
from schemas.tools.limits import (
    WAIT_SECONDS,
    BACKUP_DIR,
    BACKUP_FILE,
    CHARS_PER_TOKEN,
    INTACT_TURNS,
    LAST_CALL_STEPS,
    LAST_CALL_TOKEN_RATIO,
    BUDGET_MARGIN,
    EXIT_MARGIN_SECONDS,
    MAX_WAITS,
    MAX_CONSECUTIVE_ERRORS,
    MAX_LIMITS_CHARS,
    MAX_OBS_CHARS,
    MAX_EMPTY_RESPONSES,
    MAX_TOKENS_PER_REQUEST,
    PAUSE_BEFORE_ABORT_SECONDS,
    FALLBACK_STATUSES,
    REQUEST_TIMEOUT_SECONDS,
)
from schemas.tools.tools_agent import (
    AUTHORIZED_LLM,
    DEBUG_FALLBACK,
    FORCE_429_MODELS,
    NO_FALLBACK,
)

from .display_func import (
    show_error,
    show_key_rotation,
    show_llm_debug,
    show_pause,
    show_switch,
    show_wait,
)

NO_CODE_MESSAGE = (
    "No valid code block was found in the model's response. "
    "Reply with one Thought line, then one ```py code block."
)
LAST_CALL_MESSAGE = (
    "[Budget almost spent: {left} step(s) left. If your answer is ready, "
    "submit it now with final_answer(...).]"
)


def save_backup(state: dict, messages: list[dict],
                steps: list[StepMetrics]) -> None:
    """Save counters, history and steps so an interrupted run can resume."""
    BACKUP_DIR.mkdir(exist_ok=True)
    with open(BACKUP_FILE, "w") as file:
        json.dump(
            {
                **state,
                "messages": messages,
                "steps": [step.model_dump(mode="json") for step in steps],
            },
            file,
            indent=2,
        )


def clear_backup() -> None:
    """Delete the backup file."""
    BACKUP_FILE.unlink(missing_ok=True)


def load_backup(task_id: str) -> dict | None:
    """Return the saved state if it belongs to `task_id`, else None."""
    if not BACKUP_FILE.exists() or BACKUP_FILE.stat().st_size == 0:
        return None
    with open(BACKUP_FILE) as file:
        state = json.load(file)
    if state.get("task_id") != task_id:
        return None
    messages = state.get("messages") or []
    if messages and messages[-1]["role"] == "assistant":
        messages.pop()
    state["messages"] = messages
    state["steps"] = [
        StepMetrics.model_validate(step) for step in state.get("steps", [])]
    return state


def compact_manual(manual: str, max_chars: int = MAX_LIMITS_CHARS) -> str:
    """Truncate the manual's limits section, keeping tool signatures intact."""
    limits, _, tools = manual.partition("\n")
    tools = tools.strip("\n")
    if len(limits) > max_chars:
        limits = (
            limits[:max_chars]
            + f"... (truncated, {len(limits)} chars total)"
        )
    return f"{limits}\n\n{tools}" if tools else limits


def truncate_history(messages: list[dict],
                     last_iter: int = INTACT_TURNS,
                     max_obs_chars: int = MAX_OBS_CHARS) -> list[dict]:
    """Keep the task and the last turns intact, shorten older observations."""
    task, rest = messages[0], messages[1:]
    kept = max(last_iter, 1) * 2
    older, recent = rest[:-kept], rest[-kept:]

    view = [task]
    for message in older:
        text = message["content"]
        if message["role"] == "user" and len(text) > max_obs_chars:
            cut = len(text) - max_obs_chars
            message = {
                **message,
                "content": f"{text[:max_obs_chars]}\n[... {cut} chars "
                           "truncated]",
            }
        view.append(message)
    return view + recent


def format_observation(result: ExecutionResult) -> str:
    """Turn everything the sandbox returned into text for the LLM."""
    parts = []
    if result.stdout:
        parts.append(result.stdout.rstrip("\n"))
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    if result.error:
        parts.append(f"error: {result.error}")
    if result.timed_out:
        parts.append(
            "[timeout: execution was stopped, the output above is partial]")
    if result.truncated:
        parts.append(
            "[output truncated: print less, e.g. a slice or a summary]")
    return "\n".join(parts) or "(no output: use print() to see values)"


def fake_429(api_url: str) -> httpx.HTTPStatusError:
    """Build a provider-like 429 error without any network call."""
    request = httpx.Request("POST", api_url)
    return httpx.HTTPStatusError(
        "simulated 429 (FORCE_429_MODELS)",
        request=request,
        response=httpx.Response(429, request=request),
    )


class AgentLoop:
    """Runs the agent loop on one task and returns a SolutionOutput."""

    def __init__(self, conf: AgentLoopConf) -> None:
        self.conf = conf
        self.request_cap: int | None = None

    def switch_model(self, model: str) -> None:
        """Replace the LLM, its model name and its URL together."""
        self.request_cap = None
        self.conf.llm = make_llm(model)
        self.conf.model_name = model
        self.conf.api_url = self.conf.llm.api_url

    def time_left(self) -> float:
        """Seconds left before the deadline, output margin included."""
        return self.deadline_at - time.monotonic()

    def handle_unavailable(self, status: int | str) -> None:
        """Try the next key, then wait or switch model; raise when stuck."""
        model = self.conf.model_name
        key_env = self.conf.llm.api_key_env

        if status == 429 and self.rotator.next_key(key_env):
            show_key_rotation(*self.rotator.position(key_env), model, status)
            return

        if NO_FALLBACK and self.waits < MAX_WAITS:
            self.waits += 1
            show_wait(status, WAIT_SECONDS, model)
            time.sleep(min(WAIT_SECONDS, max(self.time_left(), 0)))
            self.rotator.reset_key(key_env)
            return

        self.exhausted.append(f"{model} ({status})")
        if (not self.fallback_models and not NO_FALLBACK and not self.paused
                and self.time_left() > PAUSE_BEFORE_ABORT_SECONDS):
            self.paused = True
            show_pause(PAUSE_BEFORE_ABORT_SECONDS)
            time.sleep(PAUSE_BEFORE_ABORT_SECONDS)
            self.fallback_models = list(AUTHORIZED_LLM)
        if not self.fallback_models:
            raise NoModelAvailableError(self.exhausted)
        self.switch_model(self.fallback_models.pop(0))
        self.rotator.reset_key(self.conf.llm.api_key_env)
        self.handover = True
        show_switch(status, self.conf.model_name, self.conf.api_url)

    def ask_model(self, step: int, messages: list[dict], start: float,
                  used_in: int, used_out: int) -> tuple:
        """Send one step's request, retrying through keys and models.

        Return (result, input tokens, output tokens, retries, time in ms).
        """
        view = self.fit_view(messages, used_in)
        self.check_budget(start, used_in, used_out)
        retries = empty = self.waits = 0
        step_in = step_out = 0
        while True:
            self.check_budget(start, used_in, used_out)
            try:
                request_start = time.monotonic()
                self.total_requests += 1
                result = self.send(view, used_out + step_out)
                elapsed_ms = (time.monotonic() - request_start) * 1000
                step_in += result.input_tokens
                step_out += result.output_tokens
                if DEBUG_FALLBACK:
                    show_llm_debug(step, self.conf.model_name,
                                   self.conf.api_url, self.system_prompt,
                                   result.text)
                if not result.text.strip() and empty < MAX_EMPTY_RESPONSES:
                    empty += 1
                    retries += 1
                    continue
                self.handover = False
                self.paused = False
                self.context += result.text
                return result, step_in, step_out, retries, elapsed_ms
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status == 413 and self.shrink_request(error.response,
                                                         view):
                    view = self.fit_view(messages, used_in)
                    retries += 1
                    continue
                if status not in FALLBACK_STATUSES:
                    raise
                if status != 503:
                    retries += 1
                self.handle_unavailable(status)
            except httpx.RequestError:
                retries += 1
                self.check_budget(start, used_in, used_out)
                self.handle_unavailable("reseau")

    def send(self, view: list[dict], used_out: int) -> LLMResult:
        """Call the current LLM once, with the handover note if needed."""
        prompt = self.system_prompt
        if self.handover:
            prompt += "\n\n" + create_newcontext(self.context, self.task)
        if self.conf.model_name in FORCE_429_MODELS:
            raise fake_429(self.conf.api_url)
        if hasattr(self.conf.llm, "timeout"):
            self.conf.llm.timeout = min(REQUEST_TIMEOUT_SECONDS,
                                        self.time_left())
        return self.conf.llm(
            prompt, view, stop=STOP_SEQUENCES,
            max_tokens=self.output_cap(used_out),
        )

    def execute(self, text: str) -> tuple[str, str, str | None]:
        """Run the code found in `text`; return input, output, final answer.
        """
        extracted = extract_code(text)
        if extracted is None:
            return "", NO_CODE_MESSAGE, None
        result = self.conf.sandbox.execute(extracted.code)
        final_answer = result.final_answer
        if final_answer is not None:
            output = result.stdout or ""
        else:
            output = format_observation(result)
        if extracted.note:
            output = f"[extraction: {extracted.note}]\n{output}"
        return extracted.code, output, final_answer

    def backup_state(self, task_id: str, used_in: int, used_out: int) -> dict:
        return {
            "total_input_tokens": used_in,
            "total_output_token": used_out,
            "total_request": self.total_requests,
            "current_context": self.context,
            "previous_model": self.conf.model_name,
            "task_id": task_id,
        }

    def run(
            self,
            task_id: str,
            benchmark: str,
            user_prompt: str,
            resume: bool = True,
    ) -> SolutionOutput:
        """Loop until final_answer() or a limit; resume=False ignores backups.
        """
        start = time.monotonic()
        deadline = float("inf")
        if self.conf.max_wall_time_seconds is not None:
            deadline = start + self.conf.max_wall_time_seconds
        if self.conf.deadline is not None:
            deadline = min(deadline, self.conf.deadline)
        self.deadline_at = deadline - EXIT_MARGIN_SECONDS

        messages: list[dict] = [{"role": "user", "content": user_prompt}]
        self.task = user_prompt
        self.system_prompt = self.conf.system_prompt
        manual = self.conf.sandbox.get_manual()
        if manual:
            self.system_prompt += "\n\n" + compact_manual(manual)

        steps: list[StepMetrics] = []
        last_error: str | None = None
        consecutive_errors = 0

        self.context = ""
        self.handover = False
        used_in = used_out = self.total_requests = 0
        previous_model: str | None = None
        backup = load_backup(task_id) if resume else None
        if backup:
            used_in = backup.get("total_input_tokens", 0)
            used_out = backup.get("total_output_token", 0)
            self.total_requests = backup.get("total_request", 0)
            previous_model = backup.get("previous_model")
            if backup["messages"]:
                messages, steps = backup["messages"], backup["steps"]
                self.context = backup.get("current_context", "")
                self.handover = True

        self.exhausted: list[str] = []
        self.paused = False
        self.rotator = TokenRotator()
        if previous_model:
            self.switch_model(previous_model)
        self.fallback_models = [] if NO_FALLBACK else [
            model for model in AUTHORIZED_LLM
            if model != self.conf.model_name]

        def output(success: bool, solution: str, iterations: int,
                   message: str | None) -> SolutionOutput:
            return self.build_output(OutputParameter(
                task_id=task_id,
                benchmark=benchmark,
                success=success,
                solution=solution,
                iterations=iterations,
                total_requests=self.total_requests,
                total_input_tokens=used_in,
                total_output_tokens=used_out,
                start=start,
                steps=steps,
                message=message,
            ))

        try:
            for step in range(len(steps) + 1, self.conf.max_iterations + 1):
                try:
                    result, step_in, step_out, retries, elapsed_ms = (
                        self.ask_model(step, messages, start, used_in,
                                       used_out))
                    used_in += step_in
                    used_out += step_out
                    messages.append(
                        {"role": "assistant", "content": result.text})
                    code, observation, final_answer = self.execute(
                        result.text)
                    messages.append({
                        "role": "user",
                        "content": f"Observation:\n{observation}"
                                   + self.last_call_note(step, used_in),
                    })
                    steps.append(StepMetrics(
                        step=step,
                        input_tokens=step_in,
                        output_tokens=step_out,
                        request_time_ms=elapsed_ms,
                        api_url=result.api_url or self.conf.api_url,
                        model_name=result.model_name or self.conf.model_name,
                        llm_output=result.text,
                        sandbox_input=code,
                        sandbox_output=observation,
                        retries=retries,
                    ))
                    if final_answer is not None:
                        clear_backup()
                        return output(True, final_answer, step, None)
                    consecutive_errors = 0
                    self.check_budget(start, used_in, used_out)
                except httpx.HTTPStatusError as error:
                    status = error.response.status_code
                    detail = error.response.text[:300]
                    show_error(f"HTTP Error: {status} "
                               f"{error.response.reason_phrase} "
                               f"{self.conf.model_name} : {detail}")
                    last_error = f"HTTPStatusError: {status} {detail}"
                    if status != 503:
                        consecutive_errors += 1
                    self.check_budget(start, used_in, used_out)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        raise ConsecutiveErrorsError(consecutive_errors,
                                                     last_error)
                except AgentLoopError:
                    raise
                except KeyboardInterrupt:
                    save_backup(self.backup_state(task_id, used_in, used_out),
                                messages, steps)
                    raise SigStopError(
                        "CTRL+C detected, stopping the agent loop.")
                except Exception as error:
                    save_backup(self.backup_state(task_id, used_in, used_out),
                                messages, steps)
                    show_error(f"Error: {error}")
                    last_error = f"{type(error).__name__}: {error}"
                    consecutive_errors += 1
                    self.check_budget(start, used_in, used_out)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        raise ConsecutiveErrorsError(consecutive_errors,
                                                     last_error)
            raise MaxIterationsError(self.conf.max_iterations, last_error)
        except SigStopError:
            raise
        except AgentLoopError as error:
            return output(False, "", len(steps), str(error))

    def last_call_note(self, step: int, used_in: int) -> str:
        """Warn the model when few steps or input tokens are left."""
        steps_left = self.conf.max_iterations - step
        limit = self.conf.max_input_tokens
        low_tokens = (limit is not None
                      and used_in >= limit * LAST_CALL_TOKEN_RATIO)
        if steps_left > LAST_CALL_STEPS and not low_tokens:
            return ""
        return "\n" + LAST_CALL_MESSAGE.format(left=steps_left)

    def shrink_request(self, response: httpx.Response,
                       view: list[dict]) -> bool:
        """Learn a smaller request cap from a 413; False if already minimal."""
        size = (len(self.system_prompt)
                + sum(len(m["content"]) for m in view)) // CHARS_PER_TOKEN
        limit = re.search(r"Limit (\d+)", response.text)
        cap = int(int(limit.group(1)) * 0.9) if limit else int(size * 0.7)
        cap = min(cap, size - 1)
        if self.request_cap is not None and cap >= self.request_cap:
            return False
        self.request_cap = cap
        return True

    def output_cap(self, used_out: int) -> int:
        """Return max_tokens for the next request from the output budget."""
        limit = self.conf.max_output_tokens
        if limit is None:
            return MAX_TOKENS_PER_REQUEST
        return max(1, min(MAX_TOKENS_PER_REQUEST, limit - used_out))

    def fit_view(self, messages: list[dict], used_in: int) -> list[dict]:
        """Largest truncated history that fits the input budget and cap."""
        limit = self.conf.max_input_tokens
        for last_iter in range(INTACT_TURNS, 0, -1):
            view = truncate_history(messages, last_iter=last_iter)
            chars = (len(self.system_prompt)
                     + sum(len(m["content"]) for m in view))
            estimate = chars // CHARS_PER_TOKEN
            in_budget = (limit is None
                         or used_in + estimate <= limit * BUDGET_MARGIN)
            under_cap = (self.request_cap is None
                         or estimate <= self.request_cap)
            if in_budget and under_cap:
                return view
        if not in_budget:
            raise MaxInputTokensError(used_in + estimate, limit)
        return view

    def check_budget(self, start: float, used_in: int,
                     used_out: int) -> None:
        """Raise a budget error when a token or time limit is reached."""
        if (self.conf.max_input_tokens is not None
                and used_in >= self.conf.max_input_tokens):
            raise MaxInputTokensError(used_in, self.conf.max_input_tokens)
        if (self.conf.max_output_tokens is not None
                and used_out >= self.conf.max_output_tokens):
            raise MaxOutputTokensError(used_out,
                                       self.conf.max_output_tokens)
        if self.time_left() <= 0:
            elapsed = time.monotonic() - start
            raise MaxWallTimeError(
                elapsed, self.conf.max_wall_time_seconds or elapsed)

    def build_output(self, params: OutputParameter) -> SolutionOutput:
        """Build the SolutionOutput written to solution.json."""
        return SolutionOutput(
            task_id=params.task_id,
            benchmark=params.benchmark,
            success=params.success,
            solution=params.solution,
            iterations=params.iterations,
            total_requests=params.total_requests,
            total_input_tokens=params.total_input_tokens,
            total_output_tokens=params.total_output_tokens,
            total_time_seconds=time.monotonic() - params.start,
            steps=params.steps,
            system_prompt=getattr(self, "system_prompt",
                                  self.conf.system_prompt),
            error=params.message,
        )
