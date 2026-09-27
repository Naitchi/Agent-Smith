"""Manual test entry point: run the agent loop on a demo or custom task.

Usage: uv run -m src [edit|lcs|puzzle|"free text task"]
"""
from __future__ import annotations

import sys

from llm import has_api_key, make_llm
from schemas import AgentLoopConf

from .agent_loop import AgentLoop
from .display_func import show_error, show_steps, show_summary

EDIT_TASK = """\
modify a file for me
"""

LCS_TASK = """\
Implement `def longest_common_subsequence(a: str, b: str) -> int` from \
scratch, \
then prove it correct by differential testing against a brute-force reference \
you also write yourself (enumerate every subsequence, only valid for short \
strings).

Method you must follow:
- Step 1: write the brute-force reference alone and print its output on three \
hand-checked cases.
- Step 2: write the fast version.
- Step 3: compare both on every pair of random strings of length <= 8 over \
the \
alphabet 'abc'. Print the FIRST mismatching pair if there is one.
- Step 4: if there is a mismatch, do not rewrite everything: print the \
intermediate DP table for that single pair, find the wrong cell, and fix that.
- Repeat step 3 until 2000 random pairs agree.
- Only then call final_answer(source) where source is the final source code \
of \
`longest_common_subsequence` as a string.

Keep each code block under 25 seconds of execution.
"""

PUZZLE_TASK = """\
A 3x3 sliding puzzle starts at ((1, 2, 3), (4, 0, 6), (7, 5, 8)) where 0 is \
the \
empty cell, and the goal is ((1, 2, 3), (4, 5, 6), (7, 8, 0)).

Explore the state space with a breadth-first search, but explore ONE DEPTH \
LEVEL PER STEP: each of your code blocks must expand exactly one frontier and \
then stop, printing the depth reached, the size of the new frontier, the \
total \
number of visited states, and whether the goal was found.

Keep the frontier and the visited set in persistent variables between steps. \
Do not restart the search from scratch at each step, and do not run the whole \
search in a single block.

When the goal is reached, call final_answer(str(depth)) with the minimum \
number \
of moves.
"""

TASKS = {
    "edit": EDIT_TASK,
    "lcs": LCS_TASK,
    "puzzle": PUZZLE_TASK,
}

DEFAULT_TASK = EDIT_TASK


def default_conf() -> AgentLoopConf:
    """Wide limits for the demo tasks, not the subject's MBPP limits."""
    return AgentLoopConf(
        make_llm("gemini-3.5-flash-lite"),
        max_iterations=45,
        max_input_tokens=200_000,
        max_output_tokens=50_000,
        max_wall_time_seconds=1_800,
    )


def main() -> None:
    if not has_api_key():
        show_error("aucune cle API dans l'environnement : remplis .env")
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
    except Exception as error:
        show_error(f"Erreur inattendue : {type(error).__name__}: {error}")
    finally:
        show_error("Fin du programme.")
