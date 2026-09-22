"""Helpers and settings shared by the MBPP and SWE-bench agent CLIs."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from collections.abc import Callable
from pathlib import Path

from llm import default_model, has_api_key, make_llm
from schemas import (
    SYSTEM_PROMPT_MBPP,
    SYSTEM_PROMPT_SWEBENCH,
    AgentLoopConf,
    MBPPTaskInput,
    SandboxConfig,
    SandboxProtocol,
    SolutionOutput,
    SWEBenchTaskInput,
)
from schemas.tools.limits import (
    MBPP_LIMITS,
    MBPP_MCP_SERVER,
    SW_BENCH_TOOLS,
    SWEBENCH_DEFAULT_TESTBED,
    SWEBENCH_LIMITS,
    SWEBENCH_SANDBOX_TIMEOUT_SECONDS,
)
from src.agent_loop import AgentLoop
from src.display_func import show_error, show_summary
from src.sandbox import Sandbox

PROCESS_START = time.monotonic()

__all__ = [
    "MBPP_LIMITS",
    "MBPP_MCP_SERVER",
    "PROCESS_START",
    "SWEBENCH_DEFAULT_TESTBED",
    "SWEBENCH_LIMITS",
    "SWEBENCH_SANDBOX_TIMEOUT_SECONDS",
    "SW_BENCH_TOOLS",
    "SYSTEM_PROMPT_MBPP",
    "SYSTEM_PROMPT_SWEBENCH",
    "AgentLoop",
    "MBPPTaskInput",
    "SWEBenchTaskInput",
    "Sandbox",
    "SandboxConfig",
    "SandboxProtocol",
    "build_user_prompt",
    "check_api_key",
    "default_conf",
    "load_task",
    "mcp_stdio_command",
    "mcp_target",
    "parse_args",
    "run_cli",
    "show_error",
    "show_summary",
    "write_output",
]


def parse_args(prog: str) -> argparse.Namespace:
    """Parse the command line shared by both agent CLIs."""
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--provider-url", default=None)
    parser.add_argument("--mcp-server", default=None,
                        help="URL of a streamable HTTP MCP server")
    parser.add_argument("--mcp-stdio", default=None,
                        help="command launching an MCP server over stdio")
    return parser.parse_args()


def mcp_target(args: argparse.Namespace, default_command: str) -> dict:
    """Pick the MCP server: --mcp-server, then --mcp-stdio, then default."""
    if args.mcp_server:
        return {"url": args.mcp_server}
    return {"command_stdio": args.mcp_stdio or default_command}


def check_api_key() -> None:
    """Stop early when no provider has an API key."""
    if not has_api_key():
        raise RuntimeError(
            "aucune cle API dans l'environnement : remplis .env")


def load_task(path: Path, model):
    """Load and validate a task file with the given task schema."""
    with open(path) as file:
        return model.model_validate(json.load(file))


def build_user_prompt(task: MBPPTaskInput | SWEBenchTaskInput) -> str:
    """Build the first user message of an MBPP or SWE-bench task."""
    if isinstance(task, MBPPTaskInput):
        tests = "\n".join(task.test_list)
        return (
            f"{task.task_definition}\n\n"
            f"Function signature:\n{task.function_definition}\n\n"
            f"Your solution must pass these tests:\n{tests}\n"
        )
    prompt = (f"Repository: {task.repo or task.instance_id}\n\n"
              f"Issue:\n{task.problem_statement}\n")
    if task.hints_text.strip():
        prompt += f"\nHints:\n{task.hints_text}\n"
    return prompt


def mcp_stdio_command(server: Path, task_file: Path,
                      env: dict[str, str] | None = None) -> str:
    """Return the shell command starting an MCP server on a task file."""
    prefix = ""
    if env:
        variables = " ".join(f"{name}={shlex.quote(value)}"
                             for name, value in env.items())
        prefix = f"env {variables} "
    return (
        f"{prefix}{shlex.quote(sys.executable)} {shlex.quote(str(server))}"
        f" --task-file {shlex.quote(str(task_file.resolve()))}"
    )


def default_conf(model_name: str | None, provider_url: str | None,
                 sandbox: Sandbox, system_prompt: str,
                 limits: dict) -> AgentLoopConf:
    """Build the agent configuration for a benchmark's limits."""
    llm = make_llm(model_name or default_model(), provider_url)
    return AgentLoopConf(
        llm=llm,
        api_url_override=provider_url,
        sandbox=sandbox,
        system_prompt=system_prompt,
        max_iterations=limits["iterations"],
        max_input_tokens=limits["input"],
        max_output_tokens=limits["output"],
        max_wall_time_seconds=limits["wall_time"],
        deadline=PROCESS_START + limits["wall_time"],
    )


def write_output(out: SolutionOutput, path: Path) -> None:
    """Write the solution as JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.model_dump_json(indent=2))


def run_cli(main: Callable[[], None]) -> None:
    """Run a CLI entry point and exit with status 1 on any error."""
    try:
        main()
    except (KeyboardInterrupt, Exception) as error:
        show_error(f"error: {error}")
        sys.exit(1)
