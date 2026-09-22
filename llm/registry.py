"""Maps each model to its provider's URL, key variable and payload."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from schemas.tools.tools_agent import (
    AUTHORIZED_GEMINI,
    AUTHORIZED_GROQ,
    AUTHORIZED_MISTRAL,
    GEMINI_API_URL,
    GROQ_API_URL,
    MISTRAL_API_URL,
)

from .provider import OpenAICompatibleProvider


@dataclass(frozen=True)
class ProviderSpec:
    """Everything that differs from one provider to another."""

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
    ProviderSpec(
        name="mistral",
        api_url=MISTRAL_API_URL,
        api_key_env="MISTRAL_API_KEY",
        keys_env="MISTRAL_API_KEYS",
        models=tuple(AUTHORIZED_MISTRAL),
    ),
)


def spec_for_model(model: str) -> ProviderSpec:
    """Return the provider serving `model`; raise ValueError if none does."""
    for provider in PROVIDERS:
        if model in provider.models:
            return provider
    known = " ; ".join(
        f"{provider.name} = {', '.join(provider.models)}"
        for provider in PROVIDERS
    )
    raise ValueError(f"modele inconnu : {model!r}. Connus : {known}")


def has_api_key() -> bool:
    """Return True if at least one provider has an API key set."""
    return any(
        os.environ.get(provider.keys_env)
        or os.environ.get(provider.api_key_env)
        for provider in PROVIDERS
    )


def make_llm(
    model: str, api_url: str | None = None
) -> OpenAICompatibleProvider:
    """Build the provider for `model`; `api_url` overrides its endpoint."""
    provider = spec_for_model(model)
    return OpenAICompatibleProvider(
        model=model,
        api_url=api_url or provider.api_url,
        api_key_env=provider.api_key_env,
        extra_payload=dict(provider.extra_payload),
    )
