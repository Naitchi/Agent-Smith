"""Petit main de test : AgentLoop avec une conf par defaut.

    uv run -m src                  # tache par defaut (uno)
    uv run -m src uno              # une tache du catalogue TASKS
    uv run -m src "ta tache ici"   # une tache libre
"""
from __future__ import annotations

import os
import sys

from llm import make_llm
from schemas import AgentLoopConf

from .agent_loop import AgentLoop
from .display_func import show_error, show_steps, show_summary

# --------------------------------------------------------------------------
# Taches de mise au point de la boucle agent.
#
# Elles ne sont PAS des taches de benchmark : elles servent a observer la
# boucle sur un grand nombre d'iterations. Le critere de selection est qu'un
# modele ne peut pas y repondre de memoire ni en un seul bloc de code : le
# cout depasse le timeout sandbox, donc l'agent doit decouper son travail,
# conserver son etat entre deux execute() et lire ses propres observations.
# --------------------------------------------------------------------------

uno = """\
tell me your model name.
"""

dos = """\
Implement `def longest_common_subsequence(a: str, b: str) -> int` from scratch, \
then prove it correct by differential testing against a brute-force reference \
you also write yourself (enumerate every subsequence, only valid for short \
strings).

Method you must follow:
- Step 1: write the brute-force reference alone and print its output on three \
hand-checked cases.
- Step 2: write the fast version.
- Step 3: compare both on every pair of random strings of length <= 8 over the \
alphabet 'abc'. Print the FIRST mismatching pair if there is one.
- Step 4: if there is a mismatch, do not rewrite everything: print the \
intermediate DP table for that single pair, find the wrong cell, and fix that.
- Repeat step 3 until 2000 random pairs agree.
- Only then call final_answer(source) where source is the final source code of \
`longest_common_subsequence` as a string.

Keep each code block under 25 seconds of execution.
"""

tres = """\
A 3x3 sliding puzzle starts at ((1, 2, 3), (4, 0, 6), (7, 5, 8)) where 0 is the \
empty cell, and the goal is ((1, 2, 3), (4, 5, 6), (7, 8, 0)).

Explore the state space with a breadth-first search, but explore ONE DEPTH \
LEVEL PER STEP: each of your code blocks must expand exactly one frontier and \
then stop, printing the depth reached, the size of the new frontier, the total \
number of visited states, and whether the goal was found.

Keep the frontier and the visited set in persistent variables between steps. \
Do not restart the search from scratch at each step, and do not run the whole \
search in a single block.

When the goal is reached, call final_answer(str(depth)) with the minimum number \
of moves.
"""

TASKS = {
    "uno": uno,
    "dos": dos,
    "tres": tres,
}

DEFAULT_TASK = uno



def default_conf() -> AgentLoopConf:
    """Conf des taches de mise au point, PAS les limites du sujet.

    Les defauts d'`AgentLoopConf` sont ceux de MBPP ; collatz/lcs/puzzle sont
    choisies pour les deborder, d'ou des limites explicitement plus larges.
    """
    return AgentLoopConf(
        make_llm("gemini-3.5-flash-lite"),
        max_iterations=45,
        max_input_tokens=200_000,
        max_output_tokens=50_000,
        max_wall_time_seconds=1_800,
    )


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        show_error("GEMINI_API_KEY absent : `make install` puis remplis .env")
        return

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg is None:
        task = DEFAULT_TASK
    else:
        task = TASKS.get(arg, arg)
    conf = default_conf()
    try:
        out = AgentLoop(conf).run(
            task_id="demo",
            benchmark="mbpp",
            user_prompt=task,
        )
    finally:
        conf.sandbox.close()

    show_steps(out)
    show_summary(out)


if __name__ == "__main__":
    try:
        main()
    except (Exception, TimeoutError) as e:
        show_error(f"Erreur inattendue : {type(e).__name__}: {e}")
    finally:
        show_error("Fin du programme.")
