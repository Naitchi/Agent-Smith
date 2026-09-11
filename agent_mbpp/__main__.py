"""CLI agent MBPP.

    uv run python -m agent_mbpp --task-file ./cache/mbpp_task.json \
                                --output ./solution.json \
                                --model-name gemini-3.5-flash \
                                --provider-url https://.../chat/completions

La cle API est lue dans l'environnement (GEMINI_API_KEYS / GROQ_API_KEYS),
jamais passee en argument : une cle en dur ou sur la ligne de commande est
un grade 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from schemas import (
    AgentLoopConf,
    GeminiLLM,
    MBPPTaskInput,
    SolutionOutput,
    SYSTEM_PROMPT_MBPP,
)

from src.agent_loop import AgentLoop

MAX_ITERATIONS = 10
MAX_INPUT_TOKENS = 6_000
MAX_OUTPUT_TOKENS = 1_500
MAX_WALL_TIME_SECONDS = 120


def load_task(path: Path) -> MBPPTaskInput:
    """Charge et valide le fichier de tache (leve si le format est mauvais)."""
    with open(path) as f:
        return MBPPTaskInput.model_validate(json.load(f))


def build_user_prompt(task: MBPPTaskInput) -> str:
    """Le premier message user : enonce + signature + tests a faire passer.

    Les tests sont donnes au modele parce qu'ils font partie de l'enonce MBPP
    (le serveur MCP les rejoue de son cote via run_tests).
    """
    tests = "\n".join(task.test_list)
    return (
        f"{task.task_definition}\n\n"
        f"Function signature:\n{task.function_definition}\n\n"
        f"Your solution must pass these tests:\n{tests}\n"
    )


def start_mcp_server(task: MBPPTaskInput, cache_dir: Path) -> Path:
    """Ecrit le fichier de tache que le serveur MCP MBPP attend.

    Contrat arrete avec bclairot (TODO 0.5) :
        python mcp_tools_mbpp.py --task-file ../cache/mbpp_task.json
    C'est l'agent qui lance le process.

    TODO(bclairot) : la Sandbox doit recevoir le chemin du serveur. Tant que
    `Sandbox(stdio=..., url=...)` ecrase `server_path`, run_tests reste
    indisponible et aucune validation MBPP n'est possible.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    task_file = cache_dir / "mbpp_task.json"
    task_file.write_text(task.model_dump_json(indent=2))
    return task_file


def default_conf(model_name: str | None, provider_url: str | None) -> AgentLoopConf:
    """Conf de l'agent, avec les limites MBPP du sujet.

    `models_name` a un seul element quand --model-name est donne : sinon
    AgentLoopConf tire au hasard dans le pool et la moulinette n'obtient pas
    le modele demande.
    """
    llm = GeminiLLM(model_name) if model_name else None
    conf = AgentLoopConf(
        llm=llm,
        system_prompt=SYSTEM_PROMPT_MBPP,
        max_iterations=MAX_ITERATIONS,
        max_input_tokens=MAX_INPUT_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        max_wall_time_seconds=MAX_WALL_TIME_SECONDS,
    )
    if provider_url:
        conf.api_url = provider_url
    return conf


def write_output(out: SolutionOutput, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.model_dump_json(indent=2))


def display(out: SolutionOutput) -> None:
    """Meme sortie lisible que src/__main__.py, pour debugger a l'oeil."""
    print("\n" + "=" * 60)
    print(f"success    : {out.success}")
    print(f"iterations : {out.iterations}   requests: {out.total_requests}")
    print(
        f"tokens     : {out.total_input_tokens}/{MAX_INPUT_TOKENS} in "
        f"/ {out.total_output_tokens}/{MAX_OUTPUT_TOKENS} out"
    )
    print(f"temps      : {out.total_time_seconds:.1f}/{MAX_WALL_TIME_SECONDS} s")
    if out.error:
        print(f"error      : {out.error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent_mbpp")
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--provider-url", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        print("aucune cle API dans l'environnement : remplis .env", file=sys.stderr)
        return 1

    task = load_task(args.task_file)
    start_mcp_server(task, Path("cache"))
    conf = default_conf(args.model_name, args.provider_url)

    try:
        out = AgentLoop(conf).run(
            task_id=str(task.task_id),
            benchmark="mbpp",
            user_prompt=build_user_prompt(task),
        )
    finally:
        conf.sandbox.close()
    if not out.solution:
        for step in reversed(out.steps):
            if step.sandbox_input:
                out.solution = step.sandbox_input
                break

    write_output(out, args.output)
    display(out)
    return 0 if out.success else 1


if __name__ == "__main__":
    sys.exit(main())
