"""Helpers and settings shared by the MBPP and SWE-bench agent CLIs."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

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
from schemas.models_config import AUTHORIZED_LLM
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


def is_http_url(value: str) -> bool:
    """Return True if `value` is an http(s) URL with a host."""
    url = urlparse(value)
    return url.scheme in ("http", "https") and bool(url.netloc)


def parse_args(prog: str) -> argparse.Namespace:
    """Parse and check the command line shared by both agent CLIs."""
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--provider-url", default=None)
    mcp = parser.add_mutually_exclusive_group()
    mcp.add_argument("--mcp-server", default=None,
                     help="URL of a streamable HTTP MCP server")
    mcp.add_argument("--mcp-stdio", default=None,
                     help="command launching an MCP server over stdio")
    args = parser.parse_args()

    if not args.task_file.is_file():
        parser.error(f"--task-file: no such file: {args.task_file}")
    if args.output.is_dir():
        parser.error(f"--output: {args.output} is a directory")
    if args.model_name is not None and args.model_name not in AUTHORIZED_LLM:
        parser.error(f"--model-name: unknown model {args.model_name!r}, "
                     f"choose from: {', '.join(AUTHORIZED_LLM)}")
    for option, value in (("--provider-url", args.provider_url),
                          ("--mcp-server", args.mcp_server)):
        if value is not None and not is_http_url(value):
            parser.error(f"{option}: not an http(s) URL: {value!r}")
    if args.mcp_stdio is not None and not args.mcp_stdio.strip():
        parser.error("--mcp-stdio: empty command")
    return args


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
    """Load and validate a task file; raise ValueError if it is broken."""
    try:
        with open(path) as file:
            return model.model_validate(json.load(file))
    except OSError as error:
        raise ValueError(
            f"{path}: cannot read task file: {error.strerror}") from None
    except UnicodeDecodeError:
        raise ValueError(f"{path}: task file is not UTF-8 text") from None
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{path}: invalid JSON (line {error.lineno}, "
            f"column {error.colno}): {error.msg}") from None
    except ValidationError as error:
        fields = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or 'root'}: {item['msg']}"
            for item in error.errors())
        raise ValueError(
            f"{path}: not a valid {model.__name__}: {fields}") from None


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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out.model_dump_json(indent=2))
    except OSError as error:
        raise RuntimeError(
            f"{path}: cannot write solution: {error.strerror}") from None


def run_cli(main: Callable[[], None]) -> None:
    """Run a CLI entry point and exit with status 1 on any error."""
    try:
        main()
    except (KeyboardInterrupt, Exception) as error:
        show_error(f"error: {error}")
        sys.exit(1)
