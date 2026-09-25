"""`uv run sandbox` — a REPL for exercising the Sandbox on its own.

Lets you poke at the sandbox's restrictions and, optionally, a connected
MCP server's tools, without an LLM in the loop at all.
"""

from __future__ import annotations

import argparse
import json
import sys

from schemas import SandboxConfig
from schemas.contract_model import SandboxProtocol

from .core import Sandbox


def main() -> None:
    """Parse CLI args, build a `Sandbox`, and run the REPL loop.

    Usage:
        uv run sandbox [config.json] [--mcp-stdio "cmd"] [--mcp-server url]

    Each line of input is executed and remembered in the same sandbox
    namespace (variables persist across lines, like across an agent's
    `execute()` calls). All sandbox restrictions (imports, filesystem,
    timeout, RAM) are active. Type ``exit`` or press Ctrl+D to leave;
    the sandbox is always closed on the way out.
    """
    parser = argparse.ArgumentParser(prog="sandbox")
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to a JSON SandBoxConfig file.",
    )
    parser.add_argument(
        "--mcp-stdio",
        default=None,
        help="Command to launch an MCP server over stdio.",
    )
    parser.add_argument(
        "--mcp-server",
        default=None,
        help="URL of an MCP server to connect to.",
    )
    sandbox: SandboxProtocol
    args = parser.parse_args()
    if args.config:
        try:
            with open(args.config, "r") as f:
                config = SandboxConfig(**json.load(f))
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            return
        sandbox = Sandbox(
            config=config, command_stdio=args.mcp_stdio, url=args.mcp_server
        )
    else:
        sandbox = Sandbox(command_stdio=args.mcp_stdio, url=args.mcp_server)
    try:
        print(
            "\nSandbox REPL. Enter the code you need to execute. Each line "
            "will be executed and remenbered. Type 'exit' to exit."
        )
        while True:
            line_of_code = input(">>>")
            if line_of_code.strip() == "exit":
                raise KeyboardInterrupt
            print(sandbox.execute(line_of_code), "\n")
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
    except Exception as e:
        print(f"\nError in sandbox: {e}", file=sys.stderr)
    finally:
        sandbox.close()
