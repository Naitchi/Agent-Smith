"""Petit main de test : AgentLoop avec une conf par défaut.

    uv run -m src                  # tâche par défaut
    uv run -m src "ta tâche ici"
"""
from __future__ import annotations

import os
import sys

from schemas import (
    AgentLoopConf,
    GEMINI_API_URL,
    GROQ_API_URL,
    GeminiLLM,
    GroqLLM,
    SolutionOutput,
    
)

from .agent_loop import AgentLoop
from .sandbox import Sandbox

DEFAULT_TASK = "Calcule la somme des nombres premiers < 100."


def default_conf() -> AgentLoopConf:
    """Conf par défaut, avec les limites MBPP du sujet."""
    return AgentLoopConf(GeminiLLM("gemini-3.1-flash-lite"))


def display(out: SolutionOutput) -> None:
    for s in out.steps:
        print(
            f"\n--- step {s.step} "
            f"({s.input_tokens} in / {s.output_tokens} out, "
            f"{s.request_time_ms:.0f} ms) ---"
        )
        print(s.sandbox_input or "(aucun bloc de code)")
        print(f"  -> {s.sandbox_output.strip()[:400]}")

    print("\n" + "=" * 60)
    print(f"success    : {out.success}")
    print(f"solution   : {out.solution!r}")
    print(f"iterations : {out.iterations}   requests: {out.total_requests}")
    print(
        f"tokens     : {out.total_input_tokens} in "
        f"/ {out.total_output_tokens} out"
    )
    print(f"temps      : {out.total_time_seconds:.1f} s")
    if out.error:
        print(f"error      : {out.error}")


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY absent : `make install` puis remplis .env")
        return 1

    task = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK
    conf = default_conf()
    try:
        out = AgentLoop(conf).run(
            task_id="demo",
            benchmark="mbpp",
            user_prompt=task,
        )
    finally:
        conf.sandbox.close()

    display(out)
    return 0 if out.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
