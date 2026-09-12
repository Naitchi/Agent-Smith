from __future__ import annotations

import argparse
import json
import sys

from schemas import SandboxConfig
from schemas.contract_model import SandboxProtocol

from .core import Sandbox


def main() -> None:
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
        # TODO voir pour tester avec du code avec des fonctions de plusieurs
        # lignes avec codeop ? ou code.InteractiveConsole ?
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
