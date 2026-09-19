from  __future__ import annotations
import time, json, os, shutil, random
import httpx
from llm import PROVIDERS, make_llm
from schemas import (AUTHORIZED_GEMINI,
                     AUTHORIZED_GROQ,
                     AgentLoopConf,
                     AgentLoopError,
                     ConsecutiveErrorsError,
                     MaxInputTokensError,
                     MaxIterationsError,
                     MaxOutputTokensError,
                     MaxWallTimeError,
                     NoModelAvailableError,
                     OutputParameter,
                     RELAIS_MODELE,
                     SigStopError,
                     STOP_SEQUENCES,
                     SolutionOutput,
                     StepMetrics,
                     extract_code
                     )
from .display_func import (show_bascule,
                           show_error,
                           show_key_rotation,
                           show_llm_debug,
                           )


from schemas.tools_agent import (BACKUP_DIR,
                                 BACKUP_FILE,
                                 CHARS_PAR_TOKEN,
                                 DEBUG_BASCULE,
                                 FORCE_429_MODELS,
                                 LAST_ITER_INTACTS,
                                 MARGE_BUDGET,
                                 MAX_CONSECUTIVE_ERRORS,
                                 MAX_MANUAL_CHARS,
                                 MAX_OBS_CHARS,
                                 MAX_TOKENS_PAR_REQUETE,
                                 STATUS_BASCULE,
                                 )


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



def compact_manual(manual: str, max_chars: int = MAX_MANUAL_CHARS) -> str:
    if len(manual) <= max_chars:
        return manual
    phrases = [f"{p.strip()}." for p in manual.split(". ") if p.strip()]
    garde = list(phrases)
    while garde and len(" ".join(garde)) > max_chars:
        garde.remove(max(garde, key=len))
    return " ".join(garde)


def tronc_message(message: list[dict], last_iter: int = LAST_ITER_INTACTS,
                  max_obs_chars: int = MAX_OBS_CHARS) -> list[dict]:
    """Vue allegee de l'historique, envoyee au LLM a la place de `message`.

    L'enonce (message[0]) et les `last_iter` derniers tours (assistant +
    observation) partent intacts ; les observations plus anciennes sont
    coupees a `max_obs_chars` avec un marqueur. `message` n'est jamais
    modifie : backup et reprise gardent l'historique complet.
    """
    tache, reste = message[0], message[1:]
    nb_intacts = max(last_iter, 1) * 2
    anciens, recents = reste[:-nb_intacts], reste[-nb_intacts:]

    vue = [tache]
    for m in anciens:
        texte = m["content"]
        if m["role"] == "user" and len(texte) > max_obs_chars:
            coupe = len(texte) - max_obs_chars
            m = {**m, "content": f"{texte[:max_obs_chars]}\n[... {coupe} chars truncated]"}
        vue.append(m)
    return vue + recents



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

    def bascule_modele(self, model: str) -> None:
        """Change de modele : llm, model_name et api_url changent ensemble."""
        self.agent_loop.llm = make_llm(model)
        self.agent_loop.model_name = model
        self.agent_loop.api_url = self.agent_loop.llm.api_url

    def run(
            self, 
            task_id: str, 
            benchmark: str, 
            user_prompt:str,
            resume: bool = True,
            ) -> SolutionOutput:
        """Deroule la boucle Thought/Code/Observation jusqu'a final_answer().

        `resume` relit le backup s'il concerne la meme tache. A laisser a False
        cote moulinette : le backup restaure aussi `prec_model`, qui primerait
        sur le `--model-name` demande.
        """
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
        backup = load_backup(task_id) if resume else None
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
        if prec_model:
            self.bascule_modele(prec_model)
        if self.agent_loop.model_name in gemini_pool:
            gemini_pool.remove(self.agent_loop.model_name)
        elif self.agent_loop.model_name in groq_pool:
            groq_pool.remove(self.agent_loop.model_name)

        provider_keys: dict[str, list[str]] = {}
        for provider in PROVIDERS:
            raw = os.environ.get(
                provider.keys_env, os.environ.get(provider.api_key_env, "")
            )
            keys = [k.strip() for k in raw.split(",") if k.strip()]
            provider_keys[provider.api_key_env] = keys
            if keys:
                os.environ[provider.api_key_env] = keys[0]
        key_index = 0
        try:
            for step in range(len(steps) + 1, self.agent_loop.max_iterations + 1):
                try:
                    vue = self.vue_dans_budget(message, self._prompt_systeme, total_input_tokens)
                    self.check_budget(start, total_input_tokens, total_output_token)
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
                            result = self.agent_loop.llm(
                                prompt_systeme, vue, stop=STOP_SEQUENCES,
                                max_tokens=self.plafond_sortie(total_output_token),
                            )
                            if DEBUG_BASCULE:
                                show_llm_debug(step, self.agent_loop.model_name,
                                               self.agent_loop.api_url,
                                               prompt_systeme, result.text)
                            relais_en_attente = None
                            current_context += result.text
                            request_conv_time = (time.monotonic() - request_start) * 1000
                            break
                        except httpx.HTTPStatusError as e:
                            status = e.response.status_code
                            if status not in STATUS_BASCULE:
                                raise
                            retries += 1
                            if status == 429:
                                key_var = self.agent_loop.llm.api_key_env
                                keys = provider_keys.get(key_var, [])
                                if key_index + 1 < len(keys):
                                    key_index += 1
                                    os.environ[key_var] = keys[key_index]
                                    show_key_rotation(key_index + 1, len(keys),
                                                      self.agent_loop.model_name)
                                    continue
                                key_index = 0
                                if keys:
                                    os.environ[key_var] = keys[0]

                            exhausted.append(
                                f"{self.agent_loop.model_name} ({status})"
                            )
                            if self.agent_loop.model_name in gemini_pool:
                                gemini_pool.remove(self.agent_loop.model_name)
                            elif self.agent_loop.model_name in groq_pool:
                                groq_pool.remove(self.agent_loop.model_name)


                            if gemini_pool:
                                next_model = random.choice(gemini_pool)
                            elif groq_pool:
                                next_model = random.choice(groq_pool)
                            else:
                                raise NoModelAvailableError(exhausted)
                            self.bascule_modele(next_model)
                            key_index = 0
                            key_var = self.agent_loop.llm.api_key_env
                            keys = provider_keys.get(key_var, [])
                            if keys:
                                os.environ[key_var] = keys[0]
                            relais_en_attente = RELAIS_MODELE
                            show_bascule(status, self.agent_loop.model_name,
                                         self.agent_loop.api_url)

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
                    show_error(f"HTTP Error: {e.response.status_code} {e.response.reason_phrase} {self.agent_loop.model_name}")
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
                    show_error(f"Error: {e}")
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

    def plafond_sortie(self, total_output_token: int) -> int:
        """`max_tokens` de la prochaine requete : le budget de sortie restant."""
        limite = self.agent_loop.max_output_tokens
        if limite is None:
            return MAX_TOKENS_PAR_REQUETE
        return max(1, min(MAX_TOKENS_PAR_REQUETE, limite - total_output_token))

    def vue_dans_budget(
            self,
            message: list[dict],
            prompt_systeme: str,
            total_input_tokens: int) -> list[dict]:
        """Plus grande vue tronquee dont la requete reste sous `max_input_tokens`.

        Reduit la fenetre (3, 2, puis 1 tour intact) tant que l'estimation de
        la requete depasse le budget restant ; leve `MaxInputTokensError`
        AVANT l'envoi si meme un seul tour ne rentre pas.
        """
        limite = self.agent_loop.max_input_tokens
        for last_iter in range(LAST_ITER_INTACTS, 0, -1):
            vue = tronc_message(message, last_iter=last_iter)
            if limite is None:
                return vue
            chars = len(prompt_systeme) + sum(len(m["content"]) for m in vue)
            estimation = chars // CHARS_PAR_TOKEN
            if total_input_tokens + estimation <= limite * MARGE_BUDGET:
                return vue
        raise MaxInputTokensError(total_input_tokens + estimation, limite)

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
