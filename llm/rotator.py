"""Rotation des cles API, par fournisseur.

La cle active est posee dans `os.environ[api_key_env]`, que le provider
relit a chaque appel (`provider.complete`) : c'est le seul point de contact
entre les deux, la boucle ne manipule plus l'environnement elle-meme.
"""

from __future__ import annotations

import os

from .registry import PROVIDERS, ProviderSpec


class TokenRotator:
    """Cles de chaque fournisseur et laquelle est active.

    Lues une fois : `keys_env` (liste separee par des virgules) d'abord,
    `api_key_env` (cle simple) sinon. Une variable vide compte comme absente.
    """

    def __init__(self, providers: tuple[ProviderSpec, ...] = PROVIDERS) -> None:
        self.keys: dict[str, list[str]] = {}
        self.index: dict[str, int] = {}
        for provider in providers:
            raw = os.environ.get(provider.keys_env) or os.environ.get(provider.api_key_env, "")
            self.keys[provider.api_key_env] = [k.strip() for k in raw.split(",") if k.strip()]
            self.premiere_cle(provider.api_key_env)

    def premiere_cle(self, key_env: str) -> None:
        """Revient a la 1re cle du fournisseur (apres une bascule, une attente)."""
        self.index[key_env] = 0
        if self.keys.get(key_env):
            os.environ[key_env] = self.keys[key_env][0]

    def cle_suivante(self, key_env: str) -> bool:
        """Passe a la cle suivante ; False s'il n'y en a plus."""
        keys = self.keys.get(key_env, [])
        index = self.index.get(key_env, 0)
        if index + 1 >= len(keys):
            return False
        self.index[key_env] = index + 1
        os.environ[key_env] = keys[index + 1]
        return True

    def position(self, key_env: str) -> tuple[int, int]:
        """(numero de la cle active, nombre de cles), pour l'affichage."""
        return self.index.get(key_env, 0) + 1, len(self.keys.get(key_env, []))
