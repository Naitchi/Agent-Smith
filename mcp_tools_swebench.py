import argparse
import json
import sys

from mcp.server import MCPServer

from schemas.swe_bench_task_input import SWEBenchTaskInput
from src.docker_manager import DockerManager


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
        if self.task:
            self.docker_manager = DockerManager(
                self.task.docker_image,
            )
        else:
            raise ValueError("Task must be provided to initialize the server.")
        self.register_tools()
        self.register_resources()
        self.register_prompts()

    def register_tools(self) -> None:
        @self.mcp.tool()
        def read_file(
            file_path: str, start_line: int = 0, end_line: int | None = None
        ):
            if end_line is None:
                return self.docker_manager.exec(f"cat -n {file_path}")
            else:
                return self.docker_manager.exec(
                    f"cat -n {file_path} | sed -n '{start_line},{end_line}p'"
                )

        @self.mcp.tool()
        def edit_file(file_path: str, old_str: str, new_str: str):
            return self.docker_manager.exec(
                f"sed -i 's/{old_str}/{new_str}/g'", workdir=file_path
            )

        @self.mcp.tool()
        def list_files(directory: str, pattern: str = "*"):
            return self.docker_manager.exec(
                f"find {directory} -name '{pattern}'"
            )

        @self.mcp.tool()
        def search_code(pattern: str, file_pattern: str = "*"):
            return self.docker_manager.exec(
                f"grep -rnw '{pattern}' --include='{file_pattern}'"
            )

        @self.mcp.tool()
        def search_function_or_class_definition_in_code(name: str):
            return self.docker_manager.exec(
                f"grep -rnw 'def {name}' --include='*.py' || grep "
                f"-rnw 'class {name}' --include='*.py'"
            )

        @self.mcp.tool()
        def find_references(name: str, filepath: str, line: int):
            return self.docker_manager.exec(
                f"grep -rnw '{name}' {filepath} | grep -v ':{line}:'"
            )

        @self.mcp.tool()
        def run_tests(): ...

        @self.mcp.tool()
        def get_patch():
            return self.docker_manager.exec("git diff")

        @self.mcp.tool()
        def run_command(command: str, workdir: str | None = None):
            return self.docker_manager.exec(command, workdir=workdir)

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
