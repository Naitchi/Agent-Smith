"""Couche LLM (lot mobenais, cf. TODO 0.7) : providers et registre.

`make_llm(model)` est le point d'entree : il rend un `LLMProvider` deja
appaire avec l'endpoint et la variable de cle de son fournisseur.
"""

from .provider import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    LLMProvider,
    OpenAICompatibleProvider,
)
from .registry import (
    PROVIDERS,
    ProviderSpec,
    make_llm,
    spec_for_model,
)

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TEMPERATURE",
    "PROVIDERS",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "ProviderSpec",
    "make_llm",
    "spec_for_model",
]
