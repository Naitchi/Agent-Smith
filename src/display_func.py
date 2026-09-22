"""Console output of the agent: summary on stdout, events on stderr."""

from __future__ import annotations

import sys

from schemas import SolutionOutput


def err(msg: str) -> None:
    print(msg, file=sys.stderr)


def show_steps(out: SolutionOutput) -> None:
    """Print every step's code and truncated observation."""
    for step in out.steps:
        print(
            f"\n--- step {step.step} "
            f"({step.input_tokens} in / {step.output_tokens} out, "
            f"{step.request_time_ms:.0f} ms) ---"
        )
        print(step.sandbox_input or "(aucun bloc de code)")
        print(f"  -> {step.sandbox_output.strip()[:400]}")


def show_summary(out: SolutionOutput, limits: dict | None = None) -> None:
    """Print the run summary, as value/limit when `limits` is given."""
    limits = limits or {}

    def ratio(value, key: str) -> str:
        return f"{value}/{limits[key]}" if key in limits else f"{value}"

    elapsed = f"{out.total_time_seconds:.1f}"
    print("\n" + "=" * 60)
    print(f"success    : {out.success}")
    print(f"solution   : {out.solution!r}")
    print(f"iterations : {out.iterations}   requests: {out.total_requests}")
    print(
        f"tokens     : {ratio(out.total_input_tokens, 'input')} in "
        f"/ {ratio(out.total_output_tokens, 'output')} out"
    )
    print(f"temps      : {ratio(elapsed, 'wall_time')} s")
    if out.error:
        print(f"error      : {out.error}")


def show_llm_debug(
        step: int, model: str, api_url: str, prompt: str, text: str) -> None:
    err(f"[step {step}] {model} ({api_url})")
    err(f"  prompt systeme : {prompt}")
    err(f"  reponse        : {text[:200]}")


def show_key_rotation(
        index: int, total: int, model: str, status: int | str) -> None:
    err(f"{status} rate limit -> token {index}/{total} sur {model}")


def show_wait(status: int | str, seconds: float, model: str) -> None:
    err(f"{status} -> attente {seconds:.0f} s sur {model} (NO_FALLBACK)")


def show_pause(seconds: float) -> None:
    err(f"tous les modeles indisponibles -> pause {seconds:.0f} s "
        "puis nouveau tour")


def show_switch(status: int | str, model: str, api_url: str) -> None:
    err(f"{status} -> bascule sur {model} ({api_url})")


def show_error(msg: str) -> None:
    err(msg)
