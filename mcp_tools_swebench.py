import argparse
import json
import sys

from mcp.server import MCPServer

import docker
from schemas.swe_bench_task_input import SWEBenchTaskInput


class MCPServerSWEBench:
    def __init__(
        self,
        task: SWEBenchTaskInput | None = None,
        timeout: int = 30,
        max_std_length: int = 1500,
    ):
        self.timeout_timer = timeout
        self.max_std_length = max_std_length
        self.task = task
        self.mcp = MCPServer("SWEBench-tools")
        self.client = docker.from_env()
        self.container = self.client.containers.run(
            "ubuntu:latest", "sleep infinity"
        )
        self.register_tools()
        self.register_resources()
        self.register_prompts()

    def register_tools(self) -> None: ...

    def register_resources(self) -> None: ...

    def register_prompts(self) -> None: ...


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="server-SWEBench")
    parser.add_argument(
        "--task-file",
        default=None,
        help="Path to a JSON task file.",
    )
    parser.add_argument(
        "--http",
        default=False,
        action="store_true",
        help="Command to launch an MCP server with http.",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="host to bind the server to (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Config the port to bind the server to (default: 8080).",
    )
    args = parser.parse_args()

    task = None
    if args.task_file:
        try:
            with open(args.task_file) as f:
                task_data = json.load(f)
            task = SWEBenchTaskInput.model_validate(task_data)
        except Exception as e:
            print(f"Error loading task file: {e}", file=sys.stderr)
            sys.exit(1)
    server = MCPServerSWEBench(task=task)

    if args.http:
        server.mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        server.mcp.run()
