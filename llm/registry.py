"""Maps each model to its provider's URL, key variable and payload.

The providers themselves are not declared here: they are built from
`models.json` by `schemas.models_config`.
"""

from __future__ import annotations

import os

from schemas.models_config import AUTHORIZED_LLM, PROVIDERS, ProviderConfig

from .provider import OpenAICompatibleProvider

# `ProviderSpec` is the historical name of a provider entry in this module.
ProviderSpec = ProviderConfig


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


def has_key(provider: ProviderSpec) -> bool:
    """Return True if `provider` has at least one API key in the env."""
    return bool(os.environ.get(provider.keys_env)
                or os.environ.get(provider.api_key_env))


def has_api_key() -> bool:
    """Return True if at least one provider has an API key set."""
    return any(has_key(provider) for provider in PROVIDERS)


def default_model() -> str:
    """First authorized model whose provider has a key in the env.

    Used when no --model-name is given: picking the first model that can
    actually answer beats drawing one at random, which may land on a model
    the provider no longer serves.
    """
    for model in AUTHORIZED_LLM:
        if has_key(spec_for_model(model)):
            return model
    return AUTHORIZED_LLM[0]


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
