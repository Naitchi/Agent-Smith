"""Ou vit la connaissance « quel modele appartient a quel fournisseur ».

Un seul endroit decide de l'URL, de la variable de cle et des extras de
payload. Ajouter OpenRouter ou Together = ajouter un `ProviderSpec`, sans
toucher ni la boucle agent ni les CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemas.tools_agent import (
    AUTHORIZED_GEMINI,
    AUTHORIZED_GROQ,
    GEMINI_API_URL,
    GROQ_API_URL,
)

from .provider import OpenAICompatibleProvider


@dataclass(frozen=True)
class ProviderSpec:
    """Tout ce qui distingue un fournisseur d'un autre.

    `keys_env` porte la liste de cles pour la rotation sur 429, avec repli
    sur `api_key_env`. `extra_payload` est par fournisseur et non global :
    Groq exige `tool_choice: "none"`, Gemini le refuse sans `tools`.
    """

    name: str
    api_url: str
    api_key_env: str
    keys_env: str
    models: tuple[str, ...]
    extra_payload: dict[str, Any] = field(default_factory=dict)


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="gemini",
        api_url=GEMINI_API_URL,
        api_key_env="GEMINI_API_KEY",
        keys_env="GEMINI_API_KEYS",
        models=tuple(AUTHORIZED_GEMINI),
    ),
    ProviderSpec(
        name="groq",
        api_url=GROQ_API_URL,
        api_key_env="GROQ_API_KEY",
        keys_env="GROQ_API_KEYS",
        models=tuple(AUTHORIZED_GROQ),
        extra_payload={"tool_choice": "none"},
    ),
)


def spec_for_model(model: str) -> ProviderSpec:
    """Rend le `ProviderSpec` du modele, ou leve si personne ne le sert.

    On refuse plutot que de deviner : sans fournisseur, on ne sait pas quelle
    cle lire, et un appel avec la mauvaise cle echoue moins clairement.
    """
    for provider in PROVIDERS:
        if model in provider.models:
            return provider
    known = " ; ".join(
        f"{provider.name} = {', '.join(provider.models)}"
        for provider in PROVIDERS
    )
    raise ValueError(f"modele inconnu : {model!r}. Connus : {known}")


def make_llm(
    model: str, api_url: str | None = None
) -> OpenAICompatibleProvider:
    """Seul point d'entree : modele, URL et variable de cle vont ensemble.

    `api_url` (c'est `--provider-url`) remplace l'endpoint par defaut du
    fournisseur ; la variable de cle reste celle du fournisseur du modele.
    """
    provider = spec_for_model(model)
    return OpenAICompatibleProvider(
        model=model,
        api_url=api_url or provider.api_url,
        api_key_env=provider.api_key_env,
        extra_payload=dict(provider.extra_payload),
    )
