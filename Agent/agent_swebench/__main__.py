"""CLI agent SWE-bench.

    uv run python -m agent_swebench --task-file ./task.json \
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
import shlex
import sys
import time
from pathlib import Path

import docker
from docker import errors as docker_errors

from llm import has_api_key, make_llm
from schemas import (
    SYSTEM_PROMPT_SWEBENCH,
    AgentLoopConf,
    SandboxConfig,
    SolutionOutput,
    SWEBenchTaskInput,
)
from schemas.tools.limits import (
    SW_BENCH_TOOLS as MCP_SERVER,
    SWEBENCH_DEFAULT_TESTBED as DEFAULT_TESTBED,
    SWEBENCH_MAX_INPUT_TOKENS as MAX_INPUT_TOKENS,
    SWEBENCH_MAX_ITERATIONS as MAX_ITERATIONS,
    SWEBENCH_MAX_OUTPUT_TOKENS as MAX_OUTPUT_TOKENS,
    SWEBENCH_MAX_WALL_TIME_SECONDS as MAX_WALL_TIME_SECONDS,
    SWEBENCH_SANDBOX_TIMEOUT_SECONDS as SANDBOX_TIMEOUT_SECONDS,
)
from src.agent_loop import AgentLoop
from src.display_func import show_error, show_summary
from src.sandbox import Sandbox


# La moulinette chronometre depuis le lancement du process, pas depuis
# `run()` : sandbox, serveur MCP (et pull d'image) comptent aussi.
PROCESS_START = time.monotonic()


def load_task(path: Path) -> SWEBenchTaskInput:
    """Charge et valide le fichier de tache (leve si le format est mauvais)."""
    with open(path) as f:
        return SWEBenchTaskInput.model_validate(json.load(f))


def build_user_prompt(task: SWEBenchTaskInput) -> str:
    """Le premier message user : depot + issue (+ indices s'il y en a).

    `eval_script` n'est pas donne au modele : c'est `run_tests()` qui le
    rejoue cote serveur, le modele n'a qu'a lire le resultat.
    """
    prompt = f"Repository: {task.repo or task.instance_id}\n\nIssue:\n{task.problem_statement}\n"
    if task.hints_text.strip():
        prompt += f"\nHints:\n{task.hints_text}\n"
    return prompt


def ensure_image(image: str) -> None:
    """Tire l'image Docker de la tache si elle n'est pas deja en local.

    `SyncMCPClient.start()` (`src/mcp_sync_client.py:102`) n'attend que 10 s
    la session MCP, et le serveur SWE-bench demarre son conteneur AVANT de
    repondre : une image de plusieurs Go tiree a ce moment-la fait expirer la
    session, et l'agent tourne ensuite sans aucun outil. Tiree ici, la
    fenetre de 10 s ne couvre plus que le demarrage du conteneur (~2 s).
    """
    client = docker.from_env()
    try:
        client.images.get(image)
    except docker_errors.ImageNotFound:
        print(f"image absente, pull de {image}...", file=sys.stderr)
        client.images.pull(image)


def mcp_stdio_command(task_file: Path) -> str:
    """Rend la commande qui lance le serveur MCP SWE-bench sur cette tache.

    Meme contrat que MBPP (TODO 0.5) : `--task-file`, lance par l'agent.
    Prefixe `env TESTBED_PATH=...` : `MCPClient` (`src/mcp_client.py:85`)
    construit `StdioServerParameters` sans `env`, et le SDK MCP ne passe alors
    au sous-processus qu'une liste blanche (HOME, PATH...) dont TESTBED_PATH
    ne fait pas partie -- sans ce prefixe, `DockerManager` ne le trouve jamais.
    """
    testbed = os.environ.get("TESTBED_PATH") or DEFAULT_TESTBED
    return (
        f"env TESTBED_PATH={shlex.quote(testbed)}"
        f" {shlex.quote(sys.executable)} {shlex.quote(str(MCP_SERVER))}"
        f" --task-file {shlex.quote(str(task_file.resolve()))}"
    )


def default_conf(
    model_name: str | None,
    provider_url: str | None,
    sandbox: Sandbox,
) -> AgentLoopConf:
    """Conf de l'agent, avec les limites SWE-bench du sujet.

    Meme raison que pour MBPP : llm et sandbox construits ici, sinon la
    moulinette n'obtient ni le `--model-name` demande ni les outils MCP.
    """
    llm = make_llm(model_name, provider_url) if model_name else None
    return AgentLoopConf(
        llm=llm,
        sandbox=sandbox,
        system_prompt=SYSTEM_PROMPT_SWEBENCH,
        max_iterations=MAX_ITERATIONS,
        max_input_tokens=MAX_INPUT_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        max_wall_time_seconds=MAX_WALL_TIME_SECONDS,
        deadline=PROCESS_START + MAX_WALL_TIME_SECONDS,
    )


def is_patch(text: str | None) -> bool:
    """Vrai si `text` ressemble a un diff git applicable.

    Rejette ce que `_format_result` cote serveur ajoute quand ca tourne mal
    (stderr, code de sortie, marqueur de troncature) : un patch tronque ou
    pollue echoue a l'application, autant le voir ici.
    """
    if not text or not text.lstrip().startswith("diff --git"):
        return False
    return not any(
        marker in text
        for marker in ("---- stderr ----", "(exit code ", "... (truncated, ")
    )


def fetch_patch(sandbox: Sandbox) -> str | None:
    """Relit le diff courant du conteneur, sans passer par le LLM.

    A appeler AVANT `sandbox.close()` : fermer la sandbox arrete le serveur
    MCP, donc le conteneur et les modifications qu'il porte.
    """
    try:
        return sandbox.execute("final_answer(get_patch())").final_answer
    except Exception as e:
        show_error(f"get_patch() de repli impossible : {e}")
        return None


def write_output(out: SolutionOutput, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.model_dump_json(indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent_swebench")
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
    ensure_image(task.docker_image)
    sandbox = Sandbox(
        command_stdio=mcp_stdio_command(args.task_file),
        config=SandboxConfig(max_execution_time_seconds=SANDBOX_TIMEOUT_SECONDS),
    )
    if not sandbox.tool_names:
        sandbox.close()
        raise RuntimeError("serveur MCP SWE-bench injoignable, aucun outil charge")
    conf = default_conf(args.model_name, args.provider_url, sandbox)

    try:
        out = AgentLoop(conf).run(
            task_id=task.instance_id,
            benchmark="swebench",
            user_prompt=build_user_prompt(task),
            resume=False,
        )
        if not is_patch(out.solution):
            patch = fetch_patch(conf.sandbox)
            if is_patch(patch):
                out.solution = patch
        # Ecrit AVANT la fermeture : arreter le conteneur peut prendre ~10 s.
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
        show_error(f"error: {e}")
        sys.exit(1)
