from __future__ import annotations

import json
import re
import time

import httpx

from llm import TokenRotator, make_llm
from schemas import (
    RELAIS_MODELE,
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
    extract_code,
)
from schemas.tools.limits import (
    ATTENTE_SECONDS,
    BACKUP_DIR,
    BACKUP_FILE,
    CHARS_PAR_TOKEN,
    LAST_ITER_INTACTS,
    MARGE_BUDGET,
    MARGE_SORTIE_SECONDS,
    MAX_ATTENTES,
    MAX_CONSECUTIVE_ERRORS,
    MAX_LIMITES_CHARS,
    MAX_OBS_CHARS,
    MAX_REPONSES_VIDES,
    MAX_TOKENS_PAR_REQUETE,
    PAUSE_AVANT_ABANDON_SECONDS,
    STATUS_BASCULE,
    TIMEOUT_REQUETE_SECONDS,
)
from schemas.tools.tools_agent import (
    AUTHORIZED_LLM,
    DEBUG_BASCULE,
    FORCE_429_MODELS,
    NO_BASCULE,
)

from .display_func import (
    show_attente,
    show_bascule,
    show_error,
    show_key_rotation,
    show_llm_debug,
    show_pause,
)


def backup_json(total_input_tokens: int, total_output_token: int, total_request: int, current_context: str, model_name: str,
                task_id: str, messages: list[dict], steps: list[StepMetrics]):
    BACKUP_DIR.mkdir(exist_ok=True)
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



def compact_manual(manual: str, max_chars: int = MAX_LIMITES_CHARS) -> str:
    """Manuel de la sandbox allege, signatures d'outils gardees INTACTES.

    `get_manual()` rend `f"{limites}\n\n{outils}"` et la section limites ne
    contient aucun retour a la ligne : le premier `\n` separe donc les deux
    sans dependre de leur redaction. Coupe structurelle et non textuelle --
    si `get_manual()` gagne un jour un `\n` en amont, on garde trop de
    verbatim, on ne perd pas les outils.

    Seules les limites sont rognees : le modele ne peut pas deviner le nom
    d'un outil, alors qu'une limite non dite se rattrape a la premiere
    observation. Elles sont coupees net, sans passer par un decoupage en
    phrases : `get_manual()` concatene des f-strings dont les morceaux ne
    tombent pas sur les fins de phrase, donc un `split(". ")` rend des
    fragments, pas des phrases -- c'est ce qui faisait disparaitre tout le
    bloc outils, vu comme une unique phrase de ~460 caracteres.

    `final_answer` est en queue de section et saute donc en premier : sans
    consequence, `SYSTEM_PROMPT` comme `SYSTEM_PROMPT_MBPP` le nomment deja.

    Marqueur aligne sur `_truncate` (`mcp_tools_swebench.py:58`) : meme
    convention des deux cotes de la frontiere MCP.
    """
    limites, _, outils = manual.partition("\n")
    outils = outils.strip("\n")
    if len(limites) > max_chars:
        limites = (
            limites[:max_chars]
            + f"... (truncated, {len(limites)} chars total)"
        )
    return f"{limites}\n\n{outils}" if outils else limites


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


def observation(exec_res: ExecutionResult) -> str:
    """Tout ce que la sandbox a rendu, mis en texte pour le LLM.

    Rien n'est jete : sur une erreur ou un timeout, la sandbox rend aussi ce
    qui a ete imprime avant, et c'est souvent ce qui explique l'erreur.
    Timeout et troncature sont dits en clair (sujet : le LLM ne doit jamais
    deviner ce qui s'est passe).
    """
    parts = []
    if exec_res.stdout:
        parts.append(exec_res.stdout.rstrip("\n"))
    if exec_res.stderr:
        parts.append(f"stderr:\n{exec_res.stderr.rstrip()}")
    if exec_res.error:
        parts.append(f"error: {exec_res.error}")
    if exec_res.timed_out:
        parts.append("[timeout: execution was stopped, the output above is partial]")
    if exec_res.truncated:
        parts.append("[output truncated: print less, e.g. a slice or a summary]")
    return "\n".join(parts) or "(no output: use print() to see values)"


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
        agent_loop_conf: AgentLoopConf
        ) -> None:
        self.agent_loop = agent_loop_conf
        # Taille max d'UNE requete (tokens estimes), apprise d'un 413.
        self._plafond_requete: int | None = None

    def bascule_modele(self, model: str) -> None:
        """Change de modele : llm, model_name et api_url changent ensemble."""
        self._plafond_requete = None  # la limite apprise etait celle de l'ancien
        self.agent_loop.llm = make_llm(model)
        self.agent_loop.model_name = model
        self.agent_loop.api_url = self.agent_loop.llm.api_url

    def delai_restant(self) -> float:
        """Secondes avant l'echeance, marge d'ecriture de `solution.json` deduite."""
        return self._fin - time.monotonic()

    def gerer_indispo(self, status: int | str) -> None:
        """Le modele n'a pas repondu (429, 5xx, reseau).

        429 : cle suivante du meme fournisseur. Sinon, ou s'il n'y a plus de
        cle : modele suivant de AUTHORIZED_LLM (NO_BASCULE : pause puis meme
        modele, MAX_ATTENTES fois). Plus aucun modele : une pause puis un
        nouveau tour complet ; si ce tour echoue aussi, abandon.
        """
        model = self.agent_loop.model_name
        key_env = self.agent_loop.llm.api_key_env

        if status == 429 and self._rotator.cle_suivante(key_env):
            show_key_rotation(*self._rotator.position(key_env), model, status)
            return

        if NO_BASCULE and self._attentes < MAX_ATTENTES:
            self._attentes += 1
            show_attente(status, ATTENTE_SECONDS, model)
            time.sleep(min(ATTENTE_SECONDS, max(self.delai_restant(), 0)))
            self._rotator.premiere_cle(key_env)
            return

        self._exhausted.append(f"{model} ({status})")
        if (not self._pool and not NO_BASCULE and not self._pause_faite
                and self.delai_restant() > PAUSE_AVANT_ABANDON_SECONDS):
            self._pause_faite = True
            show_pause(PAUSE_AVANT_ABANDON_SECONDS)
            time.sleep(PAUSE_AVANT_ABANDON_SECONDS)
            self._pool = list(AUTHORIZED_LLM)
        if not self._pool:
            raise NoModelAvailableError(self._exhausted)
        self.bascule_modele(self._pool.pop(0))
        self._rotator.premiere_cle(self.agent_loop.llm.api_key_env)
        self._relais = RELAIS_MODELE
        show_bascule(status, self.agent_loop.model_name, self.agent_loop.api_url)

    def run(
            self,
            task_id: str,
            benchmark: str,
            user_prompt: str,
            resume: bool = True,
            ) -> SolutionOutput:
        """Deroule la boucle Thought/Code/Observation jusqu'a final_answer().

        `resume` relit le backup s'il concerne la meme tache. A laisser a False
        cote moulinette : le backup restaure aussi `prec_model`, qui primerait
        sur le `--model-name` demande.
        """
        start = time.monotonic()
        fin = float("inf")
        if self.agent_loop.max_wall_time_seconds is not None:
            fin = start + self.agent_loop.max_wall_time_seconds
        if self.agent_loop.deadline is not None:
            fin = min(fin, self.agent_loop.deadline)
        self._fin = fin - MARGE_SORTIE_SECONDS

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
        self._relais: str | None = None
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
                self._relais = RELAIS_MODELE

        self._exhausted: list[str] = []
        self._pause_faite = False  # remis a False des qu'un modele repond
        self._rotator = TokenRotator()
        if prec_model:
            self.bascule_modele(prec_model)
        # Modeles de rechange, dans l'ordre de AUTHORIZED_LLM ; la cle et l'URL
        # suivent le modele (make_llm). NO_BASCULE (benchmark) : aucun.
        self._pool = [] if NO_BASCULE else [
            m for m in AUTHORIZED_LLM if m != self.agent_loop.model_name]

        try:
            for step in range(len(steps) + 1, self.agent_loop.max_iterations + 1):
                try:
                    vue = self.vue_dans_budget(message, self._prompt_systeme, total_input_tokens)
                    self.check_budget(start, total_input_tokens, total_output_token)
                    retries = vides = self._attentes = 0
                    step_in = step_out = 0
                    while True:
                        # Chaque tentative (rotation, bascule) repasse
                        # par le budget : l'echeance est verifiee ici aussi.
                        self.check_budget(start, total_input_tokens, total_output_token)
                        try:
                            request_start = time.monotonic()
                            total_request += 1
                            prompt_systeme = self._prompt_systeme
                            if self._relais:
                                prompt_systeme += "\n\n" + self._relais
                            if self.agent_loop.model_name in FORCE_429_MODELS:
                                raise _fake_429(self.agent_loop.api_url)
                            # La requete ne peut pas durer plus que le temps
                            # qu'il reste : le timeout suit l'echeance.
                            if hasattr(self.agent_loop.llm, "timeout"):
                                self.agent_loop.llm.timeout = min(
                                    TIMEOUT_REQUETE_SECONDS, self.delai_restant())
                            result = self.agent_loop.llm(
                                prompt_systeme, vue, stop=STOP_SEQUENCES,
                                max_tokens=self.plafond_sortie(total_output_token + step_out),
                            )
                            request_conv_time = (time.monotonic() - request_start) * 1000
                            step_in += result.input_tokens
                            step_out += result.output_tokens
                            if DEBUG_BASCULE:
                                show_llm_debug(step, self.agent_loop.model_name,
                                               self.agent_loop.api_url,
                                               prompt_systeme, result.text)
                            # Reponse vide : relancee, pas une iteration perdue.
                            # Ses tokens restent comptes dans le step.
                            if not result.text.strip() and vides < MAX_REPONSES_VIDES:
                                vides += 1
                                retries += 1
                                continue
                            self._relais = None
                            self._pause_faite = False
                            current_context += result.text
                            break
                        except httpx.HTTPStatusError as e:
                            status = e.response.status_code
                            # 413 : requete trop grosse pour CE provider (ex. ITPM
                            # Groq). On rabote la fenetre et on renvoie.
                            if status == 413 and self.reduire_requete(e.response, vue):
                                vue = self.vue_dans_budget(message, self._prompt_systeme, total_input_tokens)
                                retries += 1
                                continue
                            if status not in STATUS_BASCULE:
                                raise
                            if status != 503:
                                retries += 1
                            self.gerer_indispo(status)
                        except httpx.RequestError:
                            # Timeout ou coupure reseau : meme traitement qu'un
                            # 5xx, sauf si c'est l'echeance qui a coupe.
                            retries += 1
                            self.check_budget(start, total_input_tokens, total_output_token)
                            self.gerer_indispo("reseau")

                    total_input_tokens += step_in
                    total_output_token += step_out
                    message.append(
                        {
                            "role": "assistant",
                            "content": result.text
                        }
                    )
                    extracted = extract_code(result.text)
                    final_answer: str | None = None
                    if extracted is None:
                        sandbox_input = ""
                        sandbox_output = (
                            "No valid code block was found in the model's response. "
                            "Reply with one Thought line, then one ```py code block."
                        )
                    else:
                        sandbox_input = extracted.code
                        exec_res = self.agent_loop.sandbox.execute(extracted.code)
                        if exec_res.final_answer is not None:
                            final_answer = exec_res.final_answer
                            sandbox_output = exec_res.stdout or ""
                        else:
                            sandbox_output = observation(exec_res)
                        # Sujet : un bloc interprete malgre un defaut doit etre
                        # signale au LLM, avec la facon dont il l'a ete.
                        if extracted.note:
                            sandbox_output = f"[extraction: {extracted.note}]\n{sandbox_output}"
                    message.append(
                        {
                            "role": "user",
                            "content": f"Observation:\n{sandbox_output}"
                        }
                    )

                    steps.append(
                        StepMetrics(
                            step=step,
                            input_tokens=step_in,
                            output_tokens=step_out,
                            request_time_ms=request_conv_time,
                            api_url=result.api_url or self.agent_loop.api_url,
                            model_name=result.model_name or self.agent_loop.model_name,
                            llm_output=result.text,
                            sandbox_input=sandbox_input,
                            sandbox_output=sandbox_output,
                            retries=retries
                            )
                        )
                    if final_answer is not None:
                        clear_backup()
                        return self._output(
                            OutputParameter(
                                task_id=task_id,
                                benchmark=benchmark,
                                success=True,
                                solution=final_answer,
                                iterations=step,
                                total_requests=total_request,
                                total_input_tokens=total_input_tokens,
                                total_output_tokens=total_output_token,
                                start=start,
                                steps=steps,
                                message=None,
                            )
                        )
                    consecutive_errors = 0
                    self.check_budget(start, total_input_tokens, total_output_token)
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    # Le corps dit POURQUOI (ex. le 400 de gpt-oss-20b, jamais
                    # explique faute de l'avoir garde).
                    detail = e.response.text[:300]
                    show_error(f"HTTP Error: {status} {e.response.reason_phrase} {self.agent_loop.model_name} : {detail}")
                    last_error = f"HTTPStatusError: {status} {detail}"
                    if status != 503:
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
            return self._output(
                OutputParameter(
                    task_id=task_id,
                    benchmark=benchmark,
                    success=False,
                    solution="",
                    iterations=len(steps),
                    total_requests=total_request,
                    total_input_tokens=total_input_tokens,
                    total_output_tokens=total_output_token,
                    start=start,
                    steps=steps,
                    message=str(e),
                )
            )

    def reduire_requete(self, response: httpx.Response, vue: list[dict]) -> bool:
        """Apprend la taille max d'une requete d'un 413 ; False si deja au plus bas.

        La limite est lue dans le message (Groq : « Limit 7000 »), a 90 % ;
        sinon on vise 70 % de la requete refusee.
        """
        taille = (len(self._prompt_systeme) + sum(len(m["content"]) for m in vue)) // CHARS_PAR_TOKEN
        limite = re.search(r"Limit (\d+)", response.text)
        plafond = int(int(limite.group(1)) * 0.9) if limite else int(taille * 0.7)
        plafond = min(plafond, taille - 1)
        if self._plafond_requete is not None and plafond >= self._plafond_requete:
            return False
        self._plafond_requete = plafond
        return True

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

        Respecte aussi `_plafond_requete` (taille max d'une requete, apprise
        d'un 413). Reduit la fenetre (LAST_ITER_INTACTS tours intacts, puis un
        de moins, jusqu'a 1) tant que l'estimation de
        la requete depasse le budget restant ; leve `MaxInputTokensError`
        AVANT l'envoi si meme un seul tour ne rentre pas.
        """
        limite = self.agent_loop.max_input_tokens
        for last_iter in range(LAST_ITER_INTACTS, 0, -1):
            vue = tronc_message(message, last_iter=last_iter)
            chars = len(prompt_systeme) + sum(len(m["content"]) for m in vue)
            estimation = chars // CHARS_PAR_TOKEN
            dans_budget = limite is None or total_input_tokens + estimation <= limite * MARGE_BUDGET
            sous_plafond = self._plafond_requete is None or estimation <= self._plafond_requete
            if dans_budget and sous_plafond:
                return vue
        if not dans_budget:
            raise MaxInputTokensError(total_input_tokens + estimation, limite)
        # Plafond du provider hors d'atteinte meme a 1 tour : la plus petite vue.
        return vue

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
        # Echeance = min(max_wall_time, deadline du process) - marge de sortie :
        # on rend la main AVANT que la moulinette ne tue le process.
        if self.delai_restant() <= 0:
            elapsed = time.monotonic() - start
            raise MaxWallTimeError(elapsed, self.agent_loop.max_wall_time_seconds or elapsed)

    def _output(
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
