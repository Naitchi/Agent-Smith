from  __future__ import annotations
import time, json, os, shutil, random
from pathlib import Path
import httpx
from schemas import (AUTHORIZED_GEMINI,
                     AUTHORIZED_GROQ,
                     GEMINI_API_URL,
                     GROQ_API_URL,
                     AgentLoopConf,
                     AgentLoopError,
                     GeminiLLM,
                     GroqLLM,
                     ConsecutiveErrorsError,
                     MaxInputTokensError,
                     MaxIterationsError,
                     MaxOutputTokensError,
                     MaxWallTimeError,
                     OutputParameter,
                     RELAIS_MODELE,
                     SigStopError,
                     SolutionOutput,
                     StepMetrics,
                     extract_code
                     )


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT_ROOT / "backup_memory"
BACKUP_FILE = BACKUP_DIR / "backup.json"
MAX_CONSECUTIVE_ERRORS = 3


def backup_json(total_input_tokens: int, total_output_token: int, total_request: int, current_context: str, model_name: str,
                task_id: str, messages: list[dict], steps: list[StepMetrics]):
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
                "current_context": current_context,
                "prec_model": model_name,
                "task_id": task_id,
                "messages": messages,
                "steps": [s.model_dump(mode="json") for s in steps],
            },
            f,
            indent=2,
        )


def clear_backup():
    BACKUP_FILE.unlink(missing_ok=True)


def load_backup(task_id: str) -> dict | None:
    """Etat du backup, seulement s'il concerne la meme tache."""
    if not BACKUP_FILE.exists() or BACKUP_FILE.stat().st_size == 0:
        return None
    with open(BACKUP_FILE) as f:
        res = json.load(f)
    if res.get("task_id") != task_id:
        return None
    messages = res.get("messages") or []
    if messages and messages[-1]["role"] == "assistant":
        messages.pop()
    res["messages"] = messages
    res["steps"] = [StepMetrics.model_validate(s) for s in res.get("steps", [])]
    return res


MAX_MANUAL_CHARS = 700


def compact_manual(manual: str, max_chars: int = MAX_MANUAL_CHARS) -> str:
    if len(manual) <= max_chars:
        return manual
    phrases = [f"{p.strip()}." for p in manual.split(". ") if p.strip()]
    garde = list(phrases)
    while garde and len(" ".join(garde)) > max_chars:
        garde.remove(max(garde, key=len))
    return " ".join(garde)

FORCE_429_MODELS = {
    m.strip() for m in os.environ.get("FORCE_429_MODELS", "").split(",") if m.strip()
}
DEBUG_BASCULE = os.environ.get("DEBUG_BASCULE", "") not in ("", "0")


def _fake_429(api_url: str) -> httpx.HTTPStatusError:
    """Un 429 identique en forme a celui d'un provider, sans appel reseau."""
    request = httpx.Request("POST", api_url)
    return httpx.HTTPStatusError(
        "simulated 429 (FORCE_429_MODELS)",
        request=request,
        response=httpx.Response(429, request=request),
    )


class AgentLoop:
    def __init__(
        self,
        agent_loop_conf: AgentLoopConf | None
        ) -> None:
        self.agent_loop = agent_loop_conf


    def run(
            self, 
            task_id: str, 
            benchmark: str, 
            user_prompt:str,
            ) -> SolutionOutput:
        start = time.monotonic()
        message: list[dict] = [
            {
                "role": "user",
                "content": user_prompt
            }
        ]

        self._prompt_systeme = self.agent_loop.system_prompt
        manuel = self.agent_loop.sandbox.get_manual()
        if manuel:
            self._prompt_systeme += "\n\n" + compact_manual(manuel)

        steps: list[StepMetrics] = []
        last_error: str | None = None
        consecutive_errors = 0

        current_context = ""
        relais_en_attente: str | None = None
        total_input_tokens = total_output_token = total_request = 0
        prec_model: str | None = None
        backup = load_backup(task_id)
        if backup:
            total_input_tokens = backup.get("total_input_tokens", 0)
            total_output_token = backup.get("total_output_token", 0)
            total_request = backup.get("total_request", 0)
            prec_model = backup.get("prec_model")
            if backup["messages"]:
                message, steps = backup["messages"], backup["steps"]
                current_context = backup.get("current_context", "")
                relais_en_attente = RELAIS_MODELE
        gemini_pool = list(AUTHORIZED_GEMINI)
        groq_pool = list(AUTHORIZED_GROQ)
        exhausted: list[str] = []
        if prec_model in AUTHORIZED_GEMINI:
            self.agent_loop.model_name = prec_model
            self.agent_loop.api_url = GEMINI_API_URL
            self.agent_loop.llm = GeminiLLM(prec_model)
        elif prec_model in AUTHORIZED_GROQ:
            self.agent_loop.model_name = prec_model
            self.agent_loop.api_url = GROQ_API_URL
            self.agent_loop.llm = GroqLLM(prec_model)
        if self.agent_loop.model_name in gemini_pool:
            gemini_pool.remove(self.agent_loop.model_name)
        elif self.agent_loop.model_name in groq_pool:
            groq_pool.remove(self.agent_loop.model_name)

        gemini_keys = [k.strip() for k in os.environ.get(
            "GEMINI_API_KEYS", os.environ.get("GEMINI_API_KEY", "")).split(",") if k.strip()]
        groq_keys = [k.strip() for k in os.environ.get(
            "GROQ_API_KEYS", os.environ.get("GROQ_API_KEY", "")).split(",") if k.strip()]
        key_index = 0
        if gemini_keys:
            os.environ["GEMINI_API_KEY"] = gemini_keys[0]
        if groq_keys:
            os.environ["GROQ_API_KEY"] = groq_keys[0]
        try:
            for step in range(len(steps) + 1, self.agent_loop.max_iterations + 1):
                try:
                    retries = 0
                    while True:
                        try:
                            request_start = time.monotonic()
                            total_request += 1
                            prompt_systeme = self._prompt_systeme
                            if relais_en_attente:
                                prompt_systeme += "\n\n" + relais_en_attente
                            if self.agent_loop.model_name in FORCE_429_MODELS:
                                raise _fake_429(self.agent_loop.api_url)
                            result = self.agent_loop.llm(prompt_systeme, message)
                            if DEBUG_BASCULE:
                                print(f"[step {step}] {self.agent_loop.model_name} "
                                      f"({self.agent_loop.api_url})")
                                print(f"  prompt systeme : {prompt_systeme}")
                                print(f"  reponse        : {result.text[:200]}")
                            relais_en_attente = None
                            current_context += result.text
                            request_conv_time = (time.monotonic() - request_start) * 1000
                            break
                        except httpx.HTTPStatusError as e:
                            if e.response.status_code != 429:
                                raise
                            retries += 1
                            on_gemini = self.agent_loop.api_url == GEMINI_API_URL
                            keys = gemini_keys if on_gemini else groq_keys
                            key_var = "GEMINI_API_KEY" if on_gemini else "GROQ_API_KEY"
                            if key_index + 1 < len(keys):
                                key_index += 1
                                os.environ[key_var] = keys[key_index]
                                print(
                                    f"429 rate limit -> token {key_index + 1}/{len(keys)} "
                                    f"sur {self.agent_loop.model_name}"
                                )
                                continue
                            key_index = 0
                            if keys:
                                os.environ[key_var] = keys[0]

                            exhausted.append(self.agent_loop.model_name)
                            if self.agent_loop.model_name in gemini_pool:
                                gemini_pool.remove(self.agent_loop.model_name)
                            elif self.agent_loop.model_name in groq_pool:
                                groq_pool.remove(self.agent_loop.model_name)


                            if gemini_pool:
                                self.agent_loop.model_name = random.choice(gemini_pool)
                                self.agent_loop.api_url = GEMINI_API_URL
                                self.agent_loop.llm = GeminiLLM(self.agent_loop.model_name)
                            elif groq_pool:
                                self.agent_loop.model_name = random.choice(groq_pool)
                                self.agent_loop.api_url = GROQ_API_URL
                                self.agent_loop.llm = GroqLLM(self.agent_loop.model_name)
                                if groq_keys:
                                    os.environ["GROQ_API_KEY"] = groq_keys[0]
                            else:
                                raise AgentLoopError(
                                    f"plus aucun modele disponible, "
                                    f"{len(exhausted)}  rate limit -> "
                                    f"{', '.join(exhausted)}"
                                )
                            relais_en_attente = RELAIS_MODELE
                            print(
                                f"429 rate limit -> bascule sur {self.agent_loop.model_name} "
                                f"({self.agent_loop.api_url})"
                            )

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
                            retries=retries
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
                    self.check_budget(start, total_input_tokens, total_output_token)
                except httpx.HTTPStatusError as e:
                    print(f"HTTP Error: {e.response.status_code} {e.response.reason_phrase} {self.agent_loop.model_name}")
                    last_error = f"HTTPStatusError: {e.response.status_code}"
                    consecutive_errors += 1
                    self.check_budget(start, total_input_tokens, total_output_token)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        raise ConsecutiveErrorsError(consecutive_errors, last_error)
                except AgentLoopError:
                    raise
                except KeyboardInterrupt:
                    backup_json(total_input_tokens, total_output_token, total_request, current_context, self.agent_loop.model_name,
                                task_id, message, steps)
                    raise SigStopError("CTRL+C detected, stopping the agent loop.")
                except Exception as e:
                    backup_json(total_input_tokens, total_output_token, total_request, current_context, self.agent_loop.model_name,
                                task_id, message, steps)
                    print(f"Error: {e}")
                    last_error = f"{type(e).__name__}: {e}"
                    consecutive_errors += 1

                    self.check_budget(start, total_input_tokens, total_output_token)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        raise ConsecutiveErrorsError(consecutive_errors, last_error)
            raise MaxIterationsError(self.agent_loop.max_iterations, last_error)
        except SigStopError:
            raise 
        except AgentLoopError as e:
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
                    str(e)
                )
            )

    def check_budget(
            self, 
            start: float, 
            total_input_tokens: int, 
            total_output_token: int) -> None:
        """Leve une `BudgetExceededError` si une des limites est atteinte."""
        if (self.agent_loop.max_input_tokens is not None
            and total_input_tokens >= self.agent_loop.max_input_tokens):
            raise MaxInputTokensError(total_input_tokens, self.agent_loop.max_input_tokens)
        if (self.agent_loop.max_output_tokens is not None
            and total_output_token >= self.agent_loop.max_output_tokens):
            raise MaxOutputTokensError(total_output_token, self.agent_loop.max_output_tokens)
        elapsed = time.monotonic() - start
        if (
             self.agent_loop.max_wall_time_seconds is not None
             and elapsed >= self.agent_loop.max_wall_time_seconds
             ):
             raise MaxWallTimeError(elapsed, self.agent_loop.max_wall_time_seconds)

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
            system_prompt=getattr(self, "_prompt_systeme", self.agent_loop.system_prompt),
            error=output_conf.message,
        )
