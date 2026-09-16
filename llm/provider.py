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

load_dotenv()

DEFAULT_MAX_TOKENS = 2048
# 0 = on prend toujours le token le plus probable. Un agent qui rend du
# code juge par des tests veut deux runs identiques sur la meme tache :
# sinon un echec n'est pas rejouable et les modeles ne se comparent plus.
DEFAULT_TEMPERATURE = 0.0


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
        `schemas.tools_agent.STOP_SEQUENCES`, en face du prompt qui l'ecrit.
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
        timeout: float = 60.0,
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
        response.raise_for_status()
        latency_ms = (time.monotonic() - start) * 1000
        body = response.json()
        usage = body.get("usage", {})
        return LLMResult(
            text=body["choices"][0]["message"].get("content") or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
        )

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider({self.model!r}, {self.api_url!r})"
