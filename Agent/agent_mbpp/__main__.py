"""CLI agent MBPP.

    uv run python -m agent_mbpp --task-file ./task.json \
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
import shlex
import sys
import time
from pathlib import Path

from llm import has_api_key, make_llm
from schemas import (
    SYSTEM_PROMPT_MBPP,
    AgentLoopConf,
    MBPPTaskInput,
    SolutionOutput,
)
from schemas.tools.limits import (
    MBPP_MAX_INPUT_TOKENS as MAX_INPUT_TOKENS,
    MBPP_MAX_ITERATIONS as MAX_ITERATIONS,
    MBPP_MAX_OUTPUT_TOKENS as MAX_OUTPUT_TOKENS,
    MBPP_MAX_WALL_TIME_SECONDS as MAX_WALL_TIME_SECONDS,
    MBPP_MCP_SERVER as MCP_SERVER,
)
from src.agent_loop import AgentLoop
from src.display_func import show_error, show_summary
from src.sandbox import Sandbox


# La moulinette chronometre depuis le lancement du process, pas depuis
# `run()` : sandbox, serveur MCP (et pull d'image) comptent aussi.
PROCESS_START = time.monotonic()


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


def mcp_stdio_command(task_file: Path) -> str:
    """Rend la commande qui lance le serveur MCP MBPP sur cette tache.

    Contrat avec bclairot (TODO 0.5) : convention `--task-file`, et c'est
    l'agent qui lance le process. Le fichier de la moulinette est repasse tel
    quel, les deux cotes le validant avec le meme `MBPPTaskInput`. Chemins
    absolus et `shlex.quote` : `Sandbox` fait un `shlex.split`, et le serveur
    ne tourne pas depuis notre repertoire courant.
    """
    return (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(MCP_SERVER))}"
        f" --task-file {shlex.quote(str(task_file.resolve()))}"
    )


def default_conf(
    model_name: str | None,
    provider_url: str | None,
    sandbox: Sandbox,
) -> AgentLoopConf:
    """Conf de l'agent, avec les limites MBPP du sujet.

    Le llm est construit ici et non laisse au tirage d'`AgentLoopConf`, sinon
    la moulinette n'obtient pas le `--model-name` demande. Meme raison pour le
    `sandbox` : le defaut est un `Sandbox()` nu, sans serveur MCP donc sans
    `run_tests`. `--provider-url` n'a d'effet qu'avec `--model-name`, le
    modele designant le fournisseur.
    """
    llm = make_llm(model_name, provider_url) if model_name else None
    return AgentLoopConf(
        llm=llm,
        sandbox=sandbox,
        system_prompt=SYSTEM_PROMPT_MBPP,
        max_iterations=MAX_ITERATIONS,
        max_input_tokens=MAX_INPUT_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        max_wall_time_seconds=MAX_WALL_TIME_SECONDS,
        deadline=PROCESS_START + MAX_WALL_TIME_SECONDS,
    )


def write_output(out: SolutionOutput, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.model_dump_json(indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent_mbpp")
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--provider-url", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not has_api_key():
        raise RuntimeError("aucune cle API dans l'environnement : remplis .env")

    task = load_task(args.task_file)
    sandbox = Sandbox(command_stdio=mcp_stdio_command(args.task_file))
    conf = default_conf(args.model_name, args.provider_url, sandbox)

    # solution.json ecrit AVANT de fermer la sandbox : la fermeture prend du
    # temps, et un process tue apres l'ecriture a quand meme rendu sa sortie.
    try:
        out = AgentLoop(conf).run(
            task_id=str(task.task_id),
            benchmark="mbpp",
            user_prompt=build_user_prompt(task),
            resume=False,
        )
        if not out.solution:
            for step in reversed(out.steps):
                if step.sandbox_input:
                    out.solution = step.sandbox_input
                    break
        write_output(out, args.output)
    finally:
        conf.sandbox.close()
    show_summary(out, {
        "input": MAX_INPUT_TOKENS,
        "output": MAX_OUTPUT_TOKENS,
        "wall_time": MAX_WALL_TIME_SECONDS,
    })


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, Exception) as e:
        # Code de sortie non nul : la moulinette doit voir l'echec, pas un
        # agent "fini" sans solution.json.
        show_error(f"error: {e}")
        sys.exit(1)
