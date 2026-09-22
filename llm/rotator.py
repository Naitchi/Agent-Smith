"""Per-provider API key rotation."""

from __future__ import annotations

import os

from .registry import PROVIDERS, ProviderSpec


class TokenRotator:
    """Holds each provider's keys and exposes the active one in os.environ."""

    def __init__(
            self, providers: tuple[ProviderSpec, ...] = PROVIDERS) -> None:
        self.keys: dict[str, list[str]] = {}
        self.index: dict[str, int] = {}
        for provider in providers:
            raw = (os.environ.get(provider.keys_env)
                   or os.environ.get(provider.api_key_env, ""))
            self.keys[provider.api_key_env] = [
                key.strip() for key in raw.split(",") if key.strip()]
            self.reset_key(provider.api_key_env)

    def reset_key(self, key_env: str) -> None:
        """Make the provider's first key active again."""
        self.index[key_env] = 0
        if self.keys.get(key_env):
            os.environ[key_env] = self.keys[key_env][0]

    def next_key(self, key_env: str) -> bool:
        """Switch to the next key; return False when none is left."""
        keys = self.keys.get(key_env, [])
        index = self.index.get(key_env, 0)
        if index + 1 >= len(keys):
            return False
        self.index[key_env] = index + 1
        os.environ[key_env] = keys[index + 1]
        return True

    def position(self, key_env: str) -> tuple[int, int]:
        """Return (active key number, number of keys)."""
        return (self.index.get(key_env, 0) + 1,
                len(self.keys.get(key_env, [])))
