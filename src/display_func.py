"""Affichage centralise du lot agent (boucle + CLIs).

stdout : resume et detail des steps, rien d'autre.
stderr : erreurs, avertissements, rotation de cle, bascule de modele.
"""
from __future__ import annotations

import sys

from schemas import SolutionOutput


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def show_steps(out: SolutionOutput) -> None:
    for s in out.steps:
        print(
            f"\n--- step {s.step} "
            f"({s.input_tokens} in / {s.output_tokens} out, "
            f"{s.request_time_ms:.0f} ms) ---"
        )
        print(s.sandbox_input or "(aucun bloc de code)")
        print(f"  -> {s.sandbox_output.strip()[:400]}")


def show_summary(out: SolutionOutput, limits: dict | None = None) -> None:
    """Resume du run ; `limits` (cles input/output/wall_time) affiche x/limite."""
    lim = limits or {}

    def sur(val, key: str) -> str:
        return f"{val}/{lim[key]}" if key in lim else f"{val}"

    print("\n" + "=" * 60)
    print(f"success    : {out.success}")
    print(f"solution   : {out.solution!r}")
    print(f"iterations : {out.iterations}   requests: {out.total_requests}")
    print(
        f"tokens     : {sur(out.total_input_tokens, 'input')} in "
        f"/ {sur(out.total_output_tokens, 'output')} out"
    )
    print(f"temps      : {sur(f'{out.total_time_seconds:.1f}', 'wall_time')} s")
    if out.error:
        print(f"error      : {out.error}")


def show_llm_debug(step: int, model: str, api_url: str, prompt: str, text: str) -> None:
    _err(f"[step {step}] {model} ({api_url})")
    _err(f"  prompt systeme : {prompt}")
    _err(f"  reponse        : {text[:200]}")


def show_key_rotation(index: int, total: int, model: str, status: int) -> None:
    if status == 429:
        _err(f"429 rate limit -> token {index}/{total} sur {model}")
    if status == 501:
        _err(f"501 not implemented or not available -> token {index}/{total} sur {model}")


def show_bascule(status: int, model: str, api_url: str) -> None:
    _err(f"{status} -> bascule sur {model} ({api_url})")


def show_error(msg: str) -> None:
    _err(msg)
