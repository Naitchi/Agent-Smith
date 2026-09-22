"""Couche provider LLM : une abstraction, un transport.

La boucle ne connait ni Gemini ni Groq : elle recoit un `LLMProvider` et
l'appelle. Ce qui est propre a un fournisseur vient de `registry.py`.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from dotenv import load_dotenv

from schemas.llm_result import LLMResult
from schemas.tools.limits import (
    CHARS_PAR_TOKEN,
    DEFAULT_TEMPERATURE,
    MAX_TOKENS_PAR_REQUETE,
    TIMEOUT_REQUETE_SECONDS,
)

load_dotenv()

DEFAULT_MAX_TOKENS = MAX_TOKENS_PAR_REQUETE


def _generation_refusee(response: httpx.Response) -> str | None:
    """Le texte d'un appel d'outil natif refuse par le provider, sinon None.

    gpt-oss (Groq) est entraine a appeler ses propres outils (`container.exec`,
    `repo_browser.search_code`...) en JSON. Avec `tool_choice: "none"`, Groq
    repond 400 `tool_use_failed` mais renvoie la generation dans
    `failed_generation`. On la rend sous forme `<tool_call>` : l'extraction la
    convertit en appel Python, et la sandbox dit au modele si l'outil n'existe
    pas -- au lieu de trois 400 d'affilee et d'un run mort.
    """
    if response.status_code != 400:
        return None
    try:
        erreur = response.json().get("error", {})
    except ValueError:
        return None
    if erreur.get("code") != "tool_use_failed" or not erreur.get("failed_generation"):
        return None
    return f"<tool_call>{erreur['failed_generation']}</tool_call>"


class LLMProvider(ABC):
    """Interface commune a tous les fournisseurs.

    `api_url` est l'endpoint reellement appele, celui que `--provider-url`
    surcharge. `api_key_env` dit a la boucle quelle serie de cles faire
    tourner sur un 429 -- c'est lui qui fait foi, pas l'URL.
    """

    model: str
    api_url: str
    api_key_env: str

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict],
        stop: list[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> LLMResult:
        """Une completion : messages -> texte + usage."""

    def __call__(
        self,
        system: str,
        messages: list[dict],
        stop: list[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> LLMResult:
        """Forme attendue par `schemas.contract_model.LLMProtocole`.

        Les trois reglages ont un defaut, donc l'appel a deux arguments du
        protocole reste valide : un appelant qui n'en veut pas ne voit pas
        la difference. L'ordre est celui de `complete()`.

        `stop` n'a volontairement pas de defaut ici : sa valeur est dictee
        par le format du prompt, pas par le fournisseur. Elle vient de
        `schemas.tools.prompts.STOP_SEQUENCES`, en face du prompt qui l'ecrit.
        """
        return self.complete(
            system,
            messages,
            stop=stop,
            max_tokens=max_tokens,
            temperature=temperature,
        )


class OpenAICompatibleProvider(LLMProvider):
    """Tout fournisseur exposant `/chat/completions` facon OpenAI.

    Gemini, Groq, et par construction OpenRouter ou Together : seuls l'URL,
    la variable de cle et les extras de payload changent.
    """

    def __init__(
        self,
        model: str,
        api_url: str,
        api_key_env: str,
        extra_payload: dict[str, Any] | None = None,
        timeout: float = TIMEOUT_REQUETE_SECONDS,
    ) -> None:
        self.model = model
        self.api_url = api_url
        self.api_key_env = api_key_env
        self.extra_payload = extra_payload or {}
        self.timeout = timeout

    def complete(
        self,
        system: str,
        messages: list[dict],
        stop: list[str] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> LLMResult:
        """Appelle l'endpoint et rend un `LLMResult`.

        La cle est relue a chaque appel, jamais mise en cache : la rotation
        sur 429 reecrit `os.environ`, et un provider qui l'aurait capturee a
        la construction ne verrait pas le changement. Leve si elle est vide.
        """
        key = os.environ.get(self.api_key_env, "").split(",")[0].strip()
        if not key:
            raise RuntimeError(
                f"{self.api_key_env} absente de l'environnement :"
                f" impossible d'interroger {self.model}."
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}] + messages,
            **self.extra_payload,
        }
        if stop:
            payload["stop"] = stop

        start = time.monotonic()
        response = httpx.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {key}",
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000
        recupere = _generation_refusee(response)
        if recupere is not None:
            # Pas d'`usage` dans une erreur : tokens ESTIMES (chars / 4),
            # pour ne pas declarer 0 sur une requete que le provider a lue.
            chars = sum(len(m["content"]) for m in payload["messages"])
            return LLMResult(
                text=recupere,
                input_tokens=chars // CHARS_PAR_TOKEN,
                output_tokens=len(recupere) // CHARS_PAR_TOKEN,
                latency_ms=latency_ms,
                model_name=self.model,
                api_url=self.api_url,
            )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage", {})
        return LLMResult(
            text=body["choices"][0]["message"].get("content") or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            model_name=self.model,
            api_url=self.api_url,
        )

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider({self.model!r}, {self.api_url!r})"
