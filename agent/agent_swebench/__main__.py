"""SWE-bench agent CLI: solve one task file and write solution.json.

API keys are read from the environment, never from the command line.
"""
from __future__ import annotations

import os
import sys

import docker
from docker import errors as docker_errors

from agent import (
    SW_BENCH_TOOLS,
    SWEBENCH_DEFAULT_TESTBED,
    SWEBENCH_LIMITS,
    SWEBENCH_SANDBOX_TIMEOUT_SECONDS,
    SYSTEM_PROMPT_SWEBENCH,
    AgentLoop,
    Sandbox,
    SandboxConfig,
    SandboxProtocol,
    SWEBenchTaskInput,
    build_user_prompt,
    check_api_key,
    default_conf,
    load_task,
    mcp_stdio_command,
    mcp_target,
    parse_args,
    run_cli,
    show_error,
    show_summary,
    write_output,
)


def ensure_image(image: str) -> None:
    """Pull the task image first so the MCP server starts within 10 s."""
    client = docker.from_env()
    try:
        client.images.get(image)
    except docker_errors.ImageNotFound:
        print(f"image absente, pull de {image}...", file=sys.stderr)
        client.images.pull(image)


def is_patch(text: str | None) -> bool:
    """Return True if `text` looks like a clean, untruncated git diff."""
    if not text or not text.lstrip().startswith("diff --git"):
        return False
    return not any(
        marker in text
        for marker in ("---- stderr ----", "(exit code ", "... (truncated, ")
    )


def fetch_patch(sandbox: SandboxProtocol) -> str | None:
    """Read the container's current diff; call it before closing the sandbox.
    """
    try:
        return sandbox.execute("final_answer(get_patch())").final_answer
    except Exception as error:
        show_error(f"get_patch() de repli impossible : {error}")
        return None


def main() -> None:
    args = parse_args("agent_swebench")
    check_api_key()

    task = load_task(args.task_file, SWEBenchTaskInput)
    if not args.mcp_server:
        ensure_image(task.docker_image)
    testbed = os.environ.get("TESTBED_PATH") or SWEBENCH_DEFAULT_TESTBED
    default_command = mcp_stdio_command(SW_BENCH_TOOLS, args.task_file,
                                        {"TESTBED_PATH": testbed})
    sandbox = Sandbox(
        **mcp_target(args, default_command),
        config=SandboxConfig(
            max_execution_time_seconds=SWEBENCH_SANDBOX_TIMEOUT_SECONDS),
    )
    if not sandbox.tool_names:
        sandbox.close()
        raise RuntimeError(
            "serveur MCP SWE-bench injoignable, aucun outil charge")
    conf = default_conf(args.model_name, args.provider_url, sandbox,
                        SYSTEM_PROMPT_SWEBENCH, SWEBENCH_LIMITS)

    try:
        out = AgentLoop(conf).run(
            task_id=task.instance_id,
            benchmark="swebench",
            user_prompt=build_user_prompt(task),
            resume=False,
        )
        if not is_patch(out.solution):
            patch = fetch_patch(conf.sandbox)
            if patch is not None and is_patch(patch):
                out.solution = patch
        write_output(out, args.output)
    finally:
        conf.sandbox.close()
    show_summary(out, SWEBENCH_LIMITS)


if __name__ == "__main__":
    try:
        run_cli(main)
    except Exception as e:
        print(f"Erreur lors de l'exécution du script : {e}")
    finally:
        print("Exécution du script terminée.")
