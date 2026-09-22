"""LLM layer: providers, registry and API key rotation."""

from .provider import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    LLMProvider,
    OpenAICompatibleProvider,
)
from .registry import (
    PROVIDERS,
    ProviderSpec,
    has_api_key,
    make_llm,
    spec_for_model,
)
from .rotator import TokenRotator

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TEMPERATURE",
    "PROVIDERS",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "ProviderSpec",
    "TokenRotator",
    "has_api_key",
    "make_llm",
    "spec_for_model",
]
