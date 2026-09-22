"""Providers and models, read from `models.json` at the repository root.

The file holds two flat maps — one endpoint URL and one model list per
provider name — and the `ProviderConfig` objects the rest of the code uses
are built from them. The key variables follow from the provider's name
(`groq` -> `GROQ_API_KEY` / `GROQ_API_KEYS`), so adding a provider is a JSON
edit: no provider is named in this module, in the registry or in the loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_FILE = PROJECT_ROOT / "models.json"


class ProviderConfig(BaseModel):
    """One OpenAI-compatible provider and the models it serves."""

    name: str
    api_url: str
    api_key_env: str = Field(
        ..., description="env var holding one key, or several comma-separated")
    keys_env: str = Field(
        ..., description="plural env var, read before api_key_env")
    models: tuple[str, ...]
    extra_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="fields added to every request body of this provider")


class ModelsConfig(BaseModel):
    """Contents of `models.json`: the URLs, the models, the extra payloads."""

    api_urls: dict[str, str]
    models: dict[str, tuple[str, ...]]
    extra_payload: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_providers_match(self) -> ModelsConfig:
        """Every provider needs a URL and a model, and the other way round."""
        missing_models = set(self.api_urls) - set(self.models)
        missing_urls = set(self.models) - set(self.api_urls)
        if missing_models or missing_urls:
            raise ValueError(
                f"{MODELS_FILE.name}: no model for {sorted(missing_models)}, "
                f"no api_url for {sorted(missing_urls)}")
        unknown = set(self.extra_payload) - set(self.api_urls)
        if unknown:
            raise ValueError(
                f"{MODELS_FILE.name}: extra_payload for unknown provider(s) "
                f"{sorted(unknown)}")
        empty = [name for name, models in self.models.items() if not models]
        if empty:
            raise ValueError(f"{MODELS_FILE.name}: no model listed for "
                             f"{sorted(empty)}")
        duplicates = [model for model in self.model_names
                      if self.model_names.count(model) > 1]
        if duplicates:
            raise ValueError(f"{MODELS_FILE.name}: model served by two "
                             f"providers: {sorted(set(duplicates))}")
        return self

    @property
    def model_names(self) -> list[str]:
        """Every authorized model, in file order."""
        return [model
                for models in self.models.values()
                for model in models]

    @property
    def providers(self) -> tuple[ProviderConfig, ...]:
        """Build one provider per entry of `api_urls`, in file order."""
        return tuple(
            ProviderConfig(
                name=name,
                api_url=api_url,
                api_key_env=f"{name.upper()}_API_KEY",
                keys_env=f"{name.upper()}_API_KEYS",
                models=self.models[name],
                extra_payload=self.extra_payload.get(name, {}),
            )
            for name, api_url in self.api_urls.items()
        )


def load_models_config(path: Path = MODELS_FILE) -> ModelsConfig:
    """Read and validate `models.json`."""
    with open(path) as file:
        return ModelsConfig.model_validate(json.load(file))


MODELS_CONFIG = load_models_config()
PROVIDERS: tuple[ProviderConfig, ...] = MODELS_CONFIG.providers
AUTHORIZED_LLM: list[str] = MODELS_CONFIG.model_names
