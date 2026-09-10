"""Petit main de test : AgentLoop avec une conf par defaut.

    uv run -m src                  # tache par defaut (collatz)
    uv run -m src collatz          # une tache du catalogue TASKS
    uv run -m src "ta tache ici"   # une tache libre
"""
from __future__ import annotations

import os
import sys

from schemas import (
    AgentLoopConf,
    GeminiLLM,
    SolutionOutput,
    
)

from .agent_loop import AgentLoop

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
Count how many integers n in the range [1, 1000000] have a Collatz sequence \
(n -> n/2 if even, n -> 3n+1 if odd, counting steps until reaching 1) whose \
length is strictly greater than 250 steps.

Constraints you must respect, they are part of the problem:
- The sandbox kills any single code execution that runs longer than 25 seconds. \
Scanning the whole range in one execution WILL be killed, so split the range \
into chunks and process one chunk per step.
- Variables persist between your code blocks. Use that: keep your running \
counter, your current position in the range, and any memoization table in \
module-level variables so the next step resumes where you stopped.
- After each chunk, print your progress: last index processed, current count, \
and the wall-clock time that chunk took. Use those numbers to size your next \
chunk.
- Watch your memory: the sandbox is limited to 512 MB. If a memoization table \
grows too large you will get a MemoryError; adapt rather than restart.
- Before answering, re-verify on a small independent sub-range (for example \
[1, 10000]) recomputed without your memo table, and print both values.
- Only then call final_answer(str(total)) with the exact integer.

Do not guess the answer and do not answer from memory: the value must come \
from code you actually ran in this session.
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

task = {
    "collatz": uno,
    "lcs": dos,
    "puzzle": tres,
}

DEFAULT_TASK = uno



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

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg is None:
        task = DEFAULT_TASK
    else:
        task = task.get(arg, arg)
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
    try:
        main()
    except Exception as e:
        print(f"Erreur inattendue : {type(e).__name__}: {e}")
    finally:
        print("Fin du programme.")
