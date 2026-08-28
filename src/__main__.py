"""Petit main de test : AgentLoop avec une conf par défaut.

    uv run -m src                  # tâche par défaut
    uv run -m src "ta tâche ici"
"""
from __future__ import annotations

import os
import sys

from schemas import AgentLoopConf, SolutionOutput

from .agent_loop import AgentLoop
from .llm import GROQ_API_URL, GroqLLM, GEMINI_API_URL, GeminiLLM
from .sandbox import Sandbox

MODEL = "gemini-3.5-flash"

SYSTEM_PROMPT = """Tu résous des tâches de programmation en écrivant du Python.
À chaque étape, écris un unique bloc de code Python dans une fence ```py.
Utilise print() pour observer les valeurs intermédiaires.
Les variables persistent d'une étape à l'autre.
Quand tu as la réponse définitive, appelle final_answer(valeur).
"""

DEFAULT_TASK = "Calcule la somme des nombres premiers < 100."


def default_conf() -> AgentLoopConf:
    """Conf par défaut, avec les limites MBPP du sujet."""
    return AgentLoopConf(
        llm=GeminiLLM(MODEL),
        sandbox=Sandbox(),
        system_prompt=SYSTEM_PROMPT,
        max_iterations=10,
        max_input_tokens=6000,
        max_output_tokens=1500,
        max_wall_time_seconds=120,
        model_name=MODEL,
        api_url=GEMINI_API_URL,
    )


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
